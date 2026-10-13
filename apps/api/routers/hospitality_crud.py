import uuid
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import (
    User, Property, Room, Facility, Restaurant, Activity,
    RatePlan, Reservation, SupportTicket, Resident, UserRole
)
from apps.api.auth import get_current_user, verify_tenant_access, require_role
from services.realtime.broadcaster import realtime_hub

router = APIRouter(tags=["Hospitality Data Plane"])

# ----------------- SCHEMAS -----------------

class RoomCreate(BaseModel):
    organization_id: str
    property_id: str
    room_number: str
    room_type: str
    price_per_night: float
    max_occupancy: int = 2
    is_available: bool = True
    description: Optional[str] = None

class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    price_per_night: Optional[float] = None
    max_occupancy: Optional[int] = None
    is_available: Optional[bool] = None
    description: Optional[str] = None

class FacilityCreate(BaseModel):
    organization_id: str
    property_id: str
    name: str
    status: str = "Open"
    opening_time: str = "06:00 AM"
    closing_time: str = "10:00 PM"
    description: Optional[str] = None

class FacilityUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    description: Optional[str] = None

class RestaurantCreate(BaseModel):
    organization_id: str
    property_id: str
    name: str
    cuisine: Optional[str] = None
    cuisine_type: Optional[str] = None
    status: str = "Open"
    operating_hours: str = "07:00 AM - 11:00 PM"
    opening_time: str = "07:00 AM"
    closing_time: str = "11:00 PM"
    menu_json: List[Any] = []

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    cuisine: Optional[str] = None
    status: Optional[str] = None
    operating_hours: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    menu_json: Optional[List[Any]] = None

class ActivityCreate(BaseModel):
    organization_id: str
    property_id: str
    title: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = "Resort Grounds"
    time_slot: str = "05:00 PM - 06:30 PM"
    price: float = 0.0
    status: str = "Scheduled"
    description: Optional[str] = None

class ActivityUpdate(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    time_slot: Optional[str] = None
    price: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None

class RatePlanCreate(BaseModel):
    organization_id: str
    property_id: str
    name: str
    room_type: str
    price_per_night: float
    currency: str = "USD"
    is_active: bool = True

class RatePlanUpdate(BaseModel):
    name: Optional[str] = None
    room_type: Optional[str] = None
    price_per_night: Optional[float] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None

class ResidentCreate(BaseModel):
    organization_id: str
    property_id: str
    name: str
    room_number: str
    block: str = "Block A"
    status: str = "ACTIVE"
    fee_status: str = "PAID"
    check_in_date: str = "2026-01-15"
    phone: Optional[str] = None
    email: Optional[str] = None
    emergency_contact: Optional[str] = None

class ResidentUpdate(BaseModel):
    name: Optional[str] = None
    room_number: Optional[str] = None
    block: Optional[str] = None
    status: Optional[str] = None
    fee_status: Optional[str] = None
    check_in_date: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    emergency_contact: Optional[str] = None

class ReservationCreate(BaseModel):
    organization_id: str
    property_id: str
    room_id: Optional[str] = None
    room_type: Optional[str] = None
    rate_plan_id: Optional[str] = None
    customer_name: str
    customer_email: str
    check_in: str
    check_out: str
    special_requests: Optional[str] = None

class ReservationUpdate(BaseModel):
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    status: Optional[str] = None
    special_requests: Optional[str] = None

class SupportTicketCreate(BaseModel):
    organization_id: str
    property_id: str
    conversation_id: Optional[str] = None
    category: str = "General"
    room_number: Optional[str] = None
    issue_summary: Optional[str] = None
    description: Optional[str] = None
    priority: str = "HIGH"

class SupportTicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    issue_summary: Optional[str] = None
    assigned_to_user_id: Optional[str] = None

# Helper to verify property belongs to organization
async def _verify_property_ownership(property_id: str, org_id: str, db: AsyncSession):
    stmt = select(Property).where(Property.id == property_id, Property.organization_id == org_id)
    res = await db.execute(stmt)
    prop = res.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Property '{property_id}' not found for tenant")
    return prop

# ----------------- ROOMS CRUD -----------------

@router.get("/api/v1/rooms")
async def list_rooms(
    organization_id: Optional[str] = None,
    property_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Room).where(Room.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Room.property_id == property_id)
    res = await db.execute(stmt)
    rooms = res.scalars().all()
    return rooms

@router.post("/api/v1/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RoomCreate,
    current_user: User = Depends(require_role(UserRole.STAFF)),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    room = Room(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        room_number=data.room_number,
        room_type=data.room_type,
        price_per_night=data.price_per_night,
        max_occupancy=data.max_occupancy,
        is_available=data.is_available,
        description=data.description
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room

@router.get("/api/v1/rooms/{room_id}")
async def get_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Room).where(Room.id == room_id, Room.organization_id == org_id)
    res = await db.execute(stmt)
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room

@router.put("/api/v1/rooms/{room_id}")
async def update_room(
    room_id: str,
    data: RoomUpdate,
    current_user: User = Depends(require_role(UserRole.STAFF)),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Room).where(Room.id == room_id, Room.organization_id == org_id)
    res = await db.execute(stmt)
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(room, field, val)
    await db.commit()
    await db.refresh(room)
    return room

@router.delete("/api/v1/rooms/{room_id}")
async def delete_room(
    room_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Room).where(Room.id == room_id, Room.organization_id == org_id)
    res = await db.execute(stmt)
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    await db.delete(room)
    await db.commit()
    return {"status": "DELETED", "id": room_id}

# ----------------- FACILITIES CRUD -----------------

@router.get("/api/v1/facilities")
async def list_facilities(
    organization_id: Optional[str] = None,
    property_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Facility).where(Facility.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Facility.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/facilities", status_code=status.HTTP_201_CREATED)
async def create_facility(
    data: FacilityCreate,
    current_user: User = Depends(require_role(UserRole.STAFF)),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    facility = Facility(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        name=data.name,
        status=data.status,
        opening_time=data.opening_time,
        closing_time=data.closing_time,
        description=data.description
    )
    db.add(facility)
    await db.commit()
    await db.refresh(facility)
    return facility

@router.get("/api/v1/facilities/{facility_id}")
async def get_facility(facility_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Facility).where(Facility.id == facility_id, Facility.organization_id == org_id)
    res = await db.execute(stmt)
    fac = res.scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")
    return fac

@router.put("/api/v1/facilities/{facility_id}")
async def update_facility(facility_id: str, data: FacilityUpdate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Facility).where(Facility.id == facility_id, Facility.organization_id == org_id)
    res = await db.execute(stmt)
    fac = res.scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(fac, field, val)
    await db.commit()
    await db.refresh(fac)
    return fac

@router.delete("/api/v1/facilities/{facility_id}")
async def delete_facility(facility_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Facility).where(Facility.id == facility_id, Facility.organization_id == org_id)
    res = await db.execute(stmt)
    fac = res.scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")
    await db.delete(fac)
    await db.commit()
    return {"status": "DELETED", "id": facility_id}

# ----------------- RESTAURANTS CRUD -----------------

@router.get("/api/v1/restaurants")
async def list_restaurants(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Restaurant).where(Restaurant.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Restaurant.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/restaurants", status_code=status.HTTP_201_CREATED)
async def create_restaurant(data: RestaurantCreate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    actual_cuisine = data.cuisine_type or data.cuisine or "Multicuisine"
    rest = Restaurant(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        name=data.name,
        cuisine=actual_cuisine,
        status=data.status,
        operating_hours=data.operating_hours,
        opening_time=data.opening_time,
        closing_time=data.closing_time,
        menu_json=data.menu_json
    )
    db.add(rest)
    await db.commit()
    await db.refresh(rest)
    return {
        "id": rest.id,
        "organization_id": rest.organization_id,
        "property_id": rest.property_id,
        "name": rest.name,
        "cuisine": rest.cuisine,
        "cuisine_type": rest.cuisine,
        "status": rest.status,
        "operating_hours": rest.operating_hours,
        "opening_time": rest.opening_time,
        "closing_time": rest.closing_time,
        "menu_json": rest.menu_json
    }

@router.get("/api/v1/restaurants/{restaurant_id}")
async def get_restaurant(restaurant_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Restaurant).where(Restaurant.id == restaurant_id, Restaurant.organization_id == org_id)
    res = await db.execute(stmt)
    rest = res.scalar_one_or_none()
    if not rest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return rest

@router.put("/api/v1/restaurants/{restaurant_id}")
async def update_restaurant(restaurant_id: str, data: RestaurantUpdate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Restaurant).where(Restaurant.id == restaurant_id, Restaurant.organization_id == org_id)
    res = await db.execute(stmt)
    rest = res.scalar_one_or_none()
    if not rest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(rest, field, val)
    await db.commit()
    await db.refresh(rest)
    return rest

@router.delete("/api/v1/restaurants/{restaurant_id}")
async def delete_restaurant(restaurant_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Restaurant).where(Restaurant.id == restaurant_id, Restaurant.organization_id == org_id)
    res = await db.execute(stmt)
    rest = res.scalar_one_or_none()
    if not rest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    await db.delete(rest)
    await db.commit()
    return {"status": "DELETED", "id": restaurant_id}

# ----------------- ACTIVITIES CRUD -----------------

@router.get("/api/v1/activities")
async def list_activities(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Activity).where(Activity.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Activity.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/activities", status_code=status.HTTP_201_CREATED)
async def create_activity(data: ActivityCreate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    act_title = data.title or data.name or "Activity"
    act_name = data.name or data.title or "Activity"
    act = Activity(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        title=act_title,
        name=act_name,
        location=data.location,
        time_slot=data.time_slot,
        price=data.price,
        status=data.status,
        description=data.description
    )
    db.add(act)
    await db.commit()
    await db.refresh(act)
    return {
        "id": act.id,
        "organization_id": act.organization_id,
        "property_id": act.property_id,
        "title": act.title,
        "name": act.name,
        "location": act.location,
        "time_slot": act.time_slot,
        "price": act.price,
        "status": act.status,
        "description": act.description
    }

@router.get("/api/v1/activities/{activity_id}")
async def get_activity(activity_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Activity).where(Activity.id == activity_id, Activity.organization_id == org_id)
    res = await db.execute(stmt)
    act = res.scalar_one_or_none()
    if not act:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return act

@router.put("/api/v1/activities/{activity_id}")
async def update_activity(activity_id: str, data: ActivityUpdate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Activity).where(Activity.id == activity_id, Activity.organization_id == org_id)
    res = await db.execute(stmt)
    act = res.scalar_one_or_none()
    if not act:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(act, field, val)
    await db.commit()
    await db.refresh(act)
    return act

@router.delete("/api/v1/activities/{activity_id}")
async def delete_activity(activity_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Activity).where(Activity.id == activity_id, Activity.organization_id == org_id)
    res = await db.execute(stmt)
    act = res.scalar_one_or_none()
    if not act:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    await db.delete(act)
    await db.commit()
    return {"status": "DELETED", "id": activity_id}

# ----------------- RATE PLANS CRUD -----------------

@router.get("/api/v1/rate-plans")
async def list_rate_plans(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(RatePlan).where(RatePlan.organization_id == org_id)
    if property_id:
        stmt = stmt.where(RatePlan.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/rate-plans", status_code=status.HTTP_201_CREATED)
async def create_rate_plan(data: RatePlanCreate, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    rp = RatePlan(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        name=data.name,
        room_type=data.room_type,
        price_per_night=data.price_per_night,
        currency=data.currency,
        is_active=data.is_active
    )
    db.add(rp)
    await db.commit()
    await db.refresh(rp)
    return rp

@router.get("/api/v1/rate-plans/{rate_plan_id}")
async def get_rate_plan(rate_plan_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(RatePlan).where(RatePlan.id == rate_plan_id, RatePlan.organization_id == org_id)
    res = await db.execute(stmt)
    rp = res.scalar_one_or_none()
    if not rp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rate plan not found")
    return rp

@router.put("/api/v1/rate-plans/{rate_plan_id}")
async def update_rate_plan(rate_plan_id: str, data: RatePlanUpdate, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(RatePlan).where(RatePlan.id == rate_plan_id, RatePlan.organization_id == org_id)
    res = await db.execute(stmt)
    rp = res.scalar_one_or_none()
    if not rp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rate plan not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(rp, field, val)
    await db.commit()
    await db.refresh(rp)
    return rp

@router.delete("/api/v1/rate-plans/{rate_plan_id}")
async def delete_rate_plan(rate_plan_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(RatePlan).where(RatePlan.id == rate_plan_id, RatePlan.organization_id == org_id)
    res = await db.execute(stmt)
    rp = res.scalar_one_or_none()
    if not rp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rate plan not found")
    await db.delete(rp)
    await db.commit()
    return {"status": "DELETED", "id": rate_plan_id}

# ----------------- RESIDENTS CRUD -----------------

@router.get("/api/v1/residents")
async def list_residents(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Resident).where(Resident.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Resident.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/residents", status_code=status.HTTP_201_CREATED)
async def create_resident(data: ResidentCreate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    res_obj = Resident(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        name=data.name,
        room_number=data.room_number,
        block=data.block,
        status=data.status,
        fee_status=data.fee_status,
        check_in_date=data.check_in_date,
        phone=data.phone,
        email=data.email,
        emergency_contact=data.emergency_contact
    )
    db.add(res_obj)
    await db.commit()
    await db.refresh(res_obj)
    return res_obj

@router.get("/api/v1/residents/{resident_id}")
async def get_resident(resident_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Resident).where(Resident.id == resident_id, Resident.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    return r

@router.put("/api/v1/residents/{resident_id}")
async def update_resident(resident_id: str, data: ResidentUpdate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Resident).where(Resident.id == resident_id, Resident.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(r, field, val)
    await db.commit()
    await db.refresh(r)
    return r

@router.delete("/api/v1/residents/{resident_id}")
async def delete_resident(resident_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Resident).where(Resident.id == resident_id, Resident.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    await db.delete(r)
    await db.commit()
    return {"status": "DELETED", "id": resident_id}

# ----------------- RESERVATIONS CRUD -----------------

@router.get("/api/v1/reservations")
async def list_reservations(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Reservation).where(Reservation.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Reservation.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/reservations", status_code=status.HTTP_201_CREATED)
async def create_reservation(data: ReservationCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)

    try:
        d_in = date.fromisoformat(data.check_in)
        d_out = date.fromisoformat(data.check_out)
        if d_out <= d_in:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="check_out must be strictly after check_in")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD")

    num_nights = (d_out - d_in).days

    # Room Allocation
    stmt_rooms = select(Room).where(Room.property_id == data.property_id, Room.is_available == True)
    if data.room_id:
        stmt_rooms = stmt_rooms.where(Room.id == data.room_id)
    elif data.room_type:
        stmt_rooms = stmt_rooms.where(Room.room_type.ilike(f"%{data.room_type}%"))
    res_rooms = await db.execute(stmt_rooms)
    candidate_rooms = res_rooms.scalars().all()

    if not candidate_rooms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No matching rooms available")

    # Conflict check
    stmt_conflicts = select(Reservation).where(
        Reservation.property_id == data.property_id,
        Reservation.status.in_(["CONFIRMED", "MODIFIED"])
    )
    res_conf = await db.execute(stmt_conflicts)
    active_conf = res_conf.scalars().all()

    occupied_ids = set()
    for r in active_conf:
        if not (r.check_out <= data.check_in or r.check_in >= data.check_out):
            if r.room_id:
                occupied_ids.add(r.room_id)

    assigned_room = next((rm for rm in candidate_rooms if rm.id not in occupied_ids), None)
    if not assigned_room:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No vacancy for requested room and date range")

    # Rate calculation
    rate = assigned_room.price_per_night
    if data.rate_plan_id:
        stmt_rp = select(RatePlan).where(RatePlan.id == data.rate_plan_id)
        res_rp = await db.execute(stmt_rp)
        rp = res_rp.scalar_one_or_none()
        if rp:
            rate = rp.price_per_night

    total_amount = round(rate * num_nights, 2)
    res_id = str(uuid.uuid4())
    reservation = Reservation(
        id=res_id,
        organization_id=org_id,
        property_id=data.property_id,
        room_id=assigned_room.id,
        rate_plan_id=data.rate_plan_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        check_in=data.check_in,
        check_out=data.check_out,
        total_amount=total_amount,
        status="CONFIRMED",
        special_requests=data.special_requests
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return reservation

@router.get("/api/v1/reservations/{reservation_id}")
async def get_reservation(reservation_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Reservation).where(Reservation.id == reservation_id, Reservation.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return r

@router.put("/api/v1/reservations/{reservation_id}")
async def update_reservation(reservation_id: str, data: ReservationUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Reservation).where(Reservation.id == reservation_id, Reservation.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if r.status == "CANCELLED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify cancelled reservation")

    if data.check_in or data.check_out:
        new_in = data.check_in or r.check_in
        new_out = data.check_out or r.check_out
        try:
            d_in = date.fromisoformat(new_in)
            d_out = date.fromisoformat(new_out)
            if d_out <= d_in:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="check_out must be strictly after check_in")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

        num_nights = (d_out - d_in).days
        room_stmt = select(Room).where(Room.id == r.room_id)
        room_res = await db.execute(room_stmt)
        assigned_room = room_res.scalar_one_or_none()
        rate = assigned_room.price_per_night if assigned_room else 100.0
        r.check_in = new_in
        r.check_out = new_out
        r.total_amount = round(rate * num_nights, 2)
        r.status = "MODIFIED"

    if data.status:
        r.status = data.status
    if data.special_requests is not None:
        r.special_requests = data.special_requests

    await db.commit()
    await db.refresh(r)
    return r

@router.delete("/api/v1/reservations/{reservation_id}")
async def cancel_reservation(reservation_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(Reservation).where(Reservation.id == reservation_id, Reservation.organization_id == org_id)
    res = await db.execute(stmt)
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if r.status == "CANCELLED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reservation already cancelled")
    r.status = "CANCELLED"
    await db.commit()
    return {"status": "CANCELLED", "id": reservation_id}

# ----------------- SUPPORT TICKETS CRUD -----------------

@router.get("/api/v1/support-tickets")
async def list_support_tickets(organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(SupportTicket).where(SupportTicket.organization_id == org_id)
    if property_id:
        stmt = stmt.where(SupportTicket.property_id == property_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/api/v1/support-tickets", status_code=status.HTTP_201_CREATED)
async def create_support_ticket(data: SupportTicketCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, data.organization_id)
    await _verify_property_ownership(data.property_id, org_id, db)
    summary = data.issue_summary or data.description or "Support request"
    ticket = SupportTicket(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        property_id=data.property_id,
        conversation_id=data.conversation_id,
        category=data.category,
        room_number=data.room_number,
        issue_summary=summary,
        priority=data.priority,
        status="OPEN"
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket

@router.get("/api/v1/support-tickets/{ticket_id}")
async def get_support_ticket(ticket_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.organization_id == org_id)
    res = await db.execute(stmt)
    t = res.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    return t

@router.put("/api/v1/support-tickets/{ticket_id}")
async def update_support_ticket(ticket_id: str, data: SupportTicketUpdate, current_user: User = Depends(require_role(UserRole.STAFF)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.organization_id == org_id)
    res = await db.execute(stmt)
    t = res.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(t, field, val)
    await db.commit()
    await db.refresh(t)
    return t

@router.delete("/api/v1/support-tickets/{ticket_id}")
async def delete_support_ticket(ticket_id: str, current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, current_user.organization_id)
    stmt = select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.organization_id == org_id)
    res = await db.execute(stmt)
    t = res.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    await db.delete(t)
    await db.commit()
    return {"status": "DELETED", "id": ticket_id}
