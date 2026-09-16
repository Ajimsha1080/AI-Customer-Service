import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Organization, Property
from apps.api.auth import get_current_user, verify_tenant_access

router = APIRouter(prefix="/api/v1", tags=["Organizations & Properties"])

class CreateOrgRequest(BaseModel):
    name: str
    slug: str

class CreatePropertyRequest(BaseModel):
    organization_id: str
    name: str
    property_type: str = "resort"
    timezone: str = "UTC"

@router.post("/organizations")
async def create_organization(req: CreateOrgRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = f"org_{req.slug.replace('-', '_')[:20]}_{int(time.time())}"
    org = Organization(id=org_id, name=req.name, slug=req.slug)
    db.add(org)
    await db.flush()
    return {"id": org.id, "name": org.name, "slug": org.slug}

@router.get("/organizations")
async def list_organizations(limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role == "SUPER_ADMIN":
        stmt = select(Organization)
    else:
        stmt = select(Organization).where(Organization.id == current_user.organization_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    orgs = res.scalars().all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "status": o.status} for o in orgs]

@router.post("/properties")
async def create_property(req: CreatePropertyRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    prop_id = f"prop_{req.name.lower().replace(' ', '_')[:20]}_{int(time.time())}"
    prop = Property(id=prop_id, organization_id=org_id, name=req.name, property_type=req.property_type, timezone=req.timezone)
    db.add(prop)
    await db.flush()
    return {"id": prop.id, "organization_id": prop.organization_id, "name": prop.name}

@router.get("/properties")
async def list_properties(organization_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Property).where(Property.organization_id == org_id).limit(limit).offset(offset)
    res = await db.execute(stmt)
    props = res.scalars().all()
    return [{"id": p.id, "organization_id": p.organization_id, "name": p.name, "type": p.property_type} for p in props]

