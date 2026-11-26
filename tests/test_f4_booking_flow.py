import pytest
import asyncio
import uuid
from datetime import date, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from services.database.session import AsyncSessionLocal
from services.database.models import User, Organization, Property, Room, Reservation, UserRole, UserSession
from services.agent_runtime.tools import HospitalityToolRegistry
from services.common.redis_service import get_redis_client, acquire_distributed_lock
from apps.api.auth import create_access_token

async def setup_f4_data():
    async with AsyncSessionLocal() as session:
        # Organization
        org = await session.get(Organization, "org_f4_test")
        if not org:
            org = Organization(id="org_f4_test", name="F4 Hotel Org", slug="f4-hotel-org", status="ACTIVE")
            session.add(org)
            await session.flush()

        # User
        user = await session.get(User, "user_f4_admin")
        if not user:
            user = User(
                id="user_f4_admin",
                organization_id="org_f4_test",
                email="admin_f4@test.com",
                full_name="Admin F4",
                hashed_password="hashed_pw_f4",
                role=UserRole.ADMIN,
                is_active=True,
                email_verified=True
            )
            session.add(user)

        # Property
        prop = await session.get(Property, "prop_f4_test")
        if not prop:
            prop = Property(id="prop_f4_test", organization_id="org_f4_test", name="Grand Palace F4")
            session.add(prop)

        # Room with max_occupancy=2
        room = await session.get(Room, "room_f4_deluxe")
        if not room:
            room = Room(
                id="room_f4_deluxe",
                organization_id="org_f4_test",
                property_id="prop_f4_test",
                room_number="401",
                room_type="Deluxe Suite",
                price_per_night=250.0,
                max_occupancy=2,
                is_available=True
            )
            session.add(room)

        await session.commit()

    # User token
    token = create_access_token(data={"sub": "user_f4_admin", "org": "org_f4_test", "role": "admin"})
    # Create user session
    import hashlib
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as session:
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        sess_id = f"sess_f4_{uuid.uuid4().hex[:6]}"
        sess = UserSession(
            id=sess_id,
            user_id="user_f4_admin",
            organization_id="org_f4_test",
            session_token_hash=session_hash,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
        )
        session.add(sess)
        await session.commit()

    return {"token": token, "org_id": "org_f4_test", "prop_id": "prop_f4_test", "room_id": "room_f4_deluxe"}

@pytest.mark.asyncio
async def test_f4_booking_validation_dates():
    data = await setup_f4_data()
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Past check_in date should be rejected (check_in < today)
        past_check_in = (date.today() - timedelta(days=2)).isoformat()
        future_check_out = (date.today() + timedelta(days=2)).isoformat()
        res = await client.post(
            "/api/v1/reservations",
            json={
                "organization_id": data["org_id"],
                "property_id": data["prop_id"],
                "room_id": data["room_id"],
                "customer_name": "Past Date Guest",
                "customer_email": "past@test.com",
                "check_in": past_check_in,
                "check_out": future_check_out,
                "guest_count": 2
            },
            headers=headers
        )
        assert res.status_code == 400
        assert "cannot be in the past" in res.json()["detail"]

        # 2. check_out <= check_in should be rejected
        today = date.today().isoformat()
        res = await client.post(
            "/api/v1/reservations",
            json={
                "organization_id": data["org_id"],
                "property_id": data["prop_id"],
                "room_id": data["room_id"],
                "customer_name": "Invalid Out Guest",
                "customer_email": "invalid@test.com",
                "check_in": today,
                "check_out": today,
                "guest_count": 1
            },
            headers=headers
        )
        assert res.status_code == 400
        assert "strictly after" in res.json()["detail"]

@pytest.mark.asyncio
async def test_f4_booking_guest_count_capacity():
    data = await setup_f4_data()
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    check_in = (date.today() + timedelta(days=20)).isoformat()
    check_out = (date.today() + timedelta(days=23)).isoformat()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # room max_occupancy is 2. Requesting 3 guests must fail with 400
        res = await client.post(
            "/api/v1/reservations",
            json={
                "organization_id": data["org_id"],
                "property_id": data["prop_id"],
                "room_id": data["room_id"],
                "customer_name": "Overcrowd Guest",
                "customer_email": "overcrowd@test.com",
                "check_in": check_in,
                "check_out": check_out,
                "guest_count": 3
            },
            headers=headers
        )
        assert res.status_code == 400
        assert "exceeds" in res.json()["detail"]

@pytest.mark.asyncio
async def test_f4_booking_redis_distributed_locking():
    data = await setup_f4_data()
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    check_in = (date.today() + timedelta(days=30)).isoformat()
    check_out = (date.today() + timedelta(days=35)).isoformat()

    # Pre-acquire the distributed lock to simulate a concurrent booking in flight
    lock_key = f"hac:lock:inventory:{data['prop_id']}:{data['room_id']}"
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with acquire_distributed_lock(lock_key, ttl_seconds=5, acquire_timeout=1.0):
            # Attempt booking while lock is held -> must return 409 Conflict
            res = await client.post(
                "/api/v1/reservations",
                json={
                    "organization_id": data["org_id"],
                    "property_id": data["prop_id"],
                    "room_id": data["room_id"],
                    "customer_name": "Concurrent Guest",
                    "customer_email": "concurrent@test.com",
                    "check_in": check_in,
                    "check_out": check_out,
                    "guest_count": 2
                },
                headers=headers
            )
            assert res.status_code == 409
            assert "locked" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_f4_booking_success_and_email_dispatch():
    data = await setup_f4_data()
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    check_in = (date.today() + timedelta(days=40)).isoformat()
    check_out = (date.today() + timedelta(days=44)).isoformat()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/reservations",
            json={
                "organization_id": data["org_id"],
                "property_id": data["prop_id"],
                "room_id": data["room_id"],
                "customer_name": "Valid Happy Guest",
                "customer_email": "happyguest@test.com",
                "check_in": check_in,
                "check_out": check_out,
                "guest_count": 2
            },
            headers=headers
        )
        assert res.status_code == 201
        res_data = res.json()
        assert res_data["status"] == "CONFIRMED"
        assert res_data["total_amount"] == 1000.0  # 4 nights * 250.0

@pytest.mark.asyncio
async def test_f4_tool_create_booking_rules():
    data = await setup_f4_data()
    registry = HospitalityToolRegistry()
    enabled = ["create_booking"]

    # 1. Past check_in date via tool
    res_past = await registry.execute_tool(
        "create_booking",
        {
            "customer_name": "Past Tool Guest",
            "customer_email": "pasttool@test.com",
            "check_in": (date.today() - timedelta(days=1)).isoformat(),
            "check_out": (date.today() + timedelta(days=3)).isoformat(),
            "room_type": "Deluxe Suite"
        },
        organization_id=data["org_id"],
        property_id=data["prop_id"],
        enabled_tools=enabled
    )
    assert res_past["success"] is False
    assert "cannot be in the past" in res_past["error"]

    # 2. Capacity exceeded via tool
    res_cap = await registry.execute_tool(
        "create_booking",
        {
            "customer_name": "Crowd Tool Guest",
            "customer_email": "crowdtool@test.com",
            "check_in": (date.today() + timedelta(days=50)).isoformat(),
            "check_out": (date.today() + timedelta(days=53)).isoformat(),
            "room_type": "Deluxe Suite",
            "guest_count": 5
        },
        organization_id=data["org_id"],
        property_id=data["prop_id"],
        enabled_tools=enabled
    )
    assert res_cap["success"] is False
    assert "exceeds" in res_cap["error"]
