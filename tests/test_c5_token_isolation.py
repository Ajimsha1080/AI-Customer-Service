import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from apps.api.main import app
from apps.api.auth import (
    create_access_token,
    create_password_reset_token,
    create_email_verify_token,
    create_mfa_challenge_token,
    create_realtime_ticket_token,
    create_user_session
)
from services.database.session import AsyncSessionLocal
from services.database.models import User, UserSession, UserRole

@pytest.mark.asyncio
async def test_c5_token_isolation_and_get_current_user_restriction(prepare_db):
    """Regression test for C5: ensure get_current_user rejects non-login tokens."""
    transport = ASGITransport(app=app)
    user_id = "usr_demo123"

    # 1. Normal access token with token_type="access" & aud="access"
    valid_access_token = create_access_token({
        "sub": user_id,
        "email": "demo@azurehostel.com",
        "role": UserRole.STAFF.value,
        "org_id": "org_azure_group"
    })

    # 2. Special tokens
    pw_reset_token = create_password_reset_token({"sub": user_id, "email": "demo@azurehostel.com"})
    email_verify_tok = create_email_verify_token({"sub": user_id, "email": "demo@azurehostel.com"})
    mfa_challenge_tok = create_mfa_challenge_token({"sub": user_id})
    realtime_ticket_tok = create_realtime_ticket_token({"sub": user_id, "org_id": "org_azure_group"})

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Valid login access token -> 200
        res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_access_token}"})
        assert res.status_code == 200
        assert res.json()["email"] == "demo@azurehostel.com"

        # Password reset token presented as Bearer token -> MUST BE 401
        res_reset = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pw_reset_token}"})
        assert res_reset.status_code == 401

        # Email verify token presented as Bearer token -> MUST BE 401
        res_verify = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {email_verify_tok}"})
        assert res_verify.status_code == 401

        # MFA challenge token presented as Bearer token -> MUST BE 401
        res_mfa = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {mfa_challenge_tok}"})
        assert res_mfa.status_code == 401

        # Realtime ticket token presented as Bearer token -> MUST BE 401
        res_realtime = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {realtime_ticket_tok}"})
        assert res_realtime.status_code == 401

@pytest.mark.asyncio
async def test_c5_password_reset_single_use_and_session_revocation(prepare_db):
    """Test that reset tokens are single-use and password reset revokes all sessions."""
    transport = ASGITransport(app=app)
    user_id = "usr_demo123"

    # Create an active session for the user
    async with AsyncSessionLocal() as db:
        sess_token = f"sess_active_token_{uuid.uuid4().hex}"
        await create_user_session(
            db=db,
            user_id=user_id,
            org_id="org_azure_group",
            access_token=sess_token
        )
        await db.commit()

    # Generate a password reset token
    reset_tok = create_password_reset_token({
        "sub": user_id,
        "email": "demo@azurehostel.com",
        "jti": f"jti_{uuid.uuid4().hex}"
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First use -> 200 OK
        res = await client.post("/api/v1/auth/reset-password", json={
            "token": reset_tok,
            "new_password": "NewSecurePassword123!@#"
        })
        assert res.status_code == 200

        # Second use (replay) -> 400 Bad Request
        res_replay = await client.post("/api/v1/auth/reset-password", json={
            "token": reset_tok,
            "new_password": "AnotherPassword123!@#"
        })
        assert res_replay.status_code == 400

    # Verify that existing sessions were revoked
    async with AsyncSessionLocal() as db:
        res_s = await db.execute(select(UserSession).where(UserSession.user_id == user_id))
        sessions = res_s.scalars().all()
        assert len(sessions) > 0
        for s in sessions:
            assert s.is_revoked is True
