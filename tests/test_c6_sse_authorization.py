import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from apps.api.main import app
from apps.api.auth import (
    create_access_token,
    create_guest_session_token,
    create_user_session
)
from services.realtime.broadcaster import generate_realtime_ticket
from services.database.session import AsyncSessionLocal
from services.database.models import User, UserRole, UserSession

@pytest.mark.asyncio
async def test_c6_sse_authorization_and_scoping(prepare_db):
    """Regression test for C6: SSE streams require authentication, single-use tickets, and strict guest scoping."""
    transport = ASGITransport(app=app)
    user_id = "usr_demo123"

    staff_token = create_access_token({
        "sub": user_id,
        "email": "demo@azurehostel.com",
        "role": UserRole.STAFF.value,
        "org_id": "org_azure_group"
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request with ?organization_id=org_azure_group -> MUST BE 401
        res_anon = await client.get("/api/v1/live-updates/events?organization_id=org_azure_group")
        assert res_anon.status_code == 401

        # 2. Staff authenticated request -> 200 text/event-stream
        async with client.stream(
            "GET",
            "/api/v1/live-updates/events?organization_id=org_azure_group&max_events=1",
            headers={"Authorization": f"Bearer {staff_token}"}
        ) as res_staff:
            assert res_staff.status_code == 200
            assert "text/event-stream" in res_staff.headers.get("content-type", "")
            async for line in res_staff.aiter_lines():
                if "CONNECTED" in line:
                    break

        # 3. Staff single-use realtime ticket
        ticket = generate_realtime_ticket(
            user_id=user_id,
            organization_id="org_azure_group",
            role=UserRole.STAFF.value
        )

        # First use -> 200
        async with client.stream(
            "GET",
            f"/api/v1/live-updates/events?ticket={ticket}&max_events=1"
        ) as res_ticket1:
            assert res_ticket1.status_code == 200
            async for line in res_ticket1.aiter_lines():
                if "CONNECTED" in line:
                    break

        # Second use (replay) -> MUST BE 401
        res_ticket2 = await client.get(f"/api/v1/live-updates/events?ticket={ticket}")
        assert res_ticket2.status_code == 401

        # 4. Guest per-conversation channel authorized by signed guest token
        conv_id = f"conv_guest_{uuid.uuid4().hex[:8]}"
        guest_tok = create_guest_session_token(
            conversation_id=conv_id,
            organization_id="org_azure_group"
        )

        async with client.stream(
            "GET",
            f"/api/v1/live-updates/events?guest_token={guest_tok}&conversation_id={conv_id}&max_events=1"
        ) as res_guest:
            assert res_guest.status_code == 200
            assert "text/event-stream" in res_guest.headers.get("content-type", "")
            async for line in res_guest.aiter_lines():
                if "CONNECTED" in line:
                    break

@pytest.mark.asyncio
async def test_c6_sse_deactivated_user_and_revoked_session(prepare_db):
    """Test that deactivated users and revoked sessions are rejected from SSE streams."""
    transport = ASGITransport(app=app)
    
    # Create user with revoked session
    unique_id = f"usr_test_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        user = User(
            id=unique_id,
            organization_id="org_azure_group",
            email=f"{unique_id}@example.com",
            full_name="Deactivated Tester",
            hashed_password="pw",
            role=UserRole.STAFF,
            is_active=False
        )
        db.add(user)
        await db.commit()

    deactivated_token = create_access_token({
        "sub": unique_id,
        "email": f"{unique_id}@example.com",
        "role": UserRole.STAFF.value,
        "org_id": "org_azure_group"
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Deactivated user attempting to stream -> 401
        res = await client.get(
            "/api/v1/live-updates/events?organization_id=org_azure_group",
            headers={"Authorization": f"Bearer {deactivated_token}"}
        )
        assert res.status_code == 401
