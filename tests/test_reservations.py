import pytest
import asyncio
from sqlalchemy import select
from services.agent_runtime.tools import HospitalityToolRegistry
from services.database.session import AsyncSessionLocal
from services.database.models import Reservation

@pytest.mark.asyncio
async def test_reservation_lifecycle_and_db_persistence():
    registry = HospitalityToolRegistry()
    org_id = "org_azure_group"
    prop_id = "prop_azure_palm_resort"
    enabled_tools = ["create_booking", "modify_booking", "cancel_booking", "check_room_availability"]

    # 1. Create booking
    book_res = await registry.execute_tool(
        tool_name="create_booking",
        tool_args={
            "customer_name": "Test Guest Resident",
            "customer_email": "testguest@residence.com",
            "check_in": "2026-10-01",
            "check_out": "2026-10-05",
            "room_type": "Single Bed Room"
        },
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=enabled_tools
    )

    assert book_res["success"] is True
    booking_id = book_res["result"]["booking_id"]
    assert booking_id.startswith("RES-")
    assert book_res["result"]["status"] == "CONFIRMED"

    # Verify DB record created
    async with AsyncSessionLocal() as session:
        stmt = select(Reservation).where(Reservation.id == booking_id)
        res = await session.execute(stmt)
        db_res = res.scalar_one_or_none()
        assert db_res is not None
        assert db_res.customer_name == "Test Guest Resident"
        assert db_res.status == "CONFIRMED"

    # 2. Modify booking
    mod_res = await registry.execute_tool(
        tool_name="modify_booking",
        tool_args={
            "booking_id": booking_id,
            "check_in": "2026-10-02",
            "check_out": "2026-10-06"
        },
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=enabled_tools
    )

    assert mod_res["success"] is True
    assert mod_res["result"]["status"] == "MODIFIED"

    # Verify DB record updated
    async with AsyncSessionLocal() as session:
        stmt = select(Reservation).where(Reservation.id == booking_id)
        res = await session.execute(stmt)
        db_res = res.scalar_one_or_none()
        assert db_res is not None
        assert db_res.status == "MODIFIED"
        assert db_res.check_in == "2026-10-02"

    # 3. Cancel booking
    cancel_res = await registry.execute_tool(
        tool_name="cancel_booking",
        tool_args={"booking_id": booking_id},
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=enabled_tools
    )

    assert cancel_res["success"] is True
    assert cancel_res["result"]["status"] == "CANCELLED"

    # Verify DB record updated to CANCELLED
    async with AsyncSessionLocal() as session:
        stmt = select(Reservation).where(Reservation.id == booking_id)
        res = await session.execute(stmt)
        db_res = res.scalar_one_or_none()
        assert db_res is not None
        assert db_res.status == "CANCELLED"
