import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import select

from apps.api.main import app
from apps.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token_async,
    revoke_user_session,
    revoke_token_hash,
    create_user_session,
    _hash_token,
    get_current_user
)
from services.database.models import User, Organization, UserRole, UserSession

@pytest.mark.asyncio
async def test_h4_refresh_token_rotation_and_reuse_detection(db_session):
    """
    H4: Rotate refresh tokens on every use.
    When an already consumed refresh token is reused, revoke the entire token family.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create test user
        org_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        email = f"user_{uuid.uuid4().hex[:6]}@example.com"
        org = Organization(id=org_id, name="Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        user = User(
            id=user_id,
            organization_id=org_id,
            email=email,
            hashed_password="hashed_pwd",
            full_name="Rotation User",
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(org)
        db_session.add(user)
        await db_session.commit()

        # Step 1: Issue initial refresh token
        initial_refresh_token = create_refresh_token({"sub": user.id})
        payload_1 = await decode_refresh_token_async(initial_refresh_token, db=db_session)
        family_id = payload_1.get("family_id")
        assert family_id is not None

        # Step 2: Use initial refresh token to obtain rotated token pair
        resp1 = await ac.post("/api/v1/auth/refresh", json={"refresh_token": initial_refresh_token})
        assert resp1.status_code == 200, resp1.text
        tokens1 = resp1.json()
        new_refresh_token_1 = tokens1["refresh_token"]
        assert new_refresh_token_1 != initial_refresh_token

        # Verify rotated token has the same family_id
        payload_2 = await decode_refresh_token_async(new_refresh_token_1, db=db_session)
        assert payload_2.get("family_id") == family_id

        # Step 3: Attempting to REUSE initial_refresh_token must trigger reuse detection
        resp_reuse = await ac.post("/api/v1/auth/refresh", json={"refresh_token": initial_refresh_token})
        assert resp_reuse.status_code == 401
        assert "reuse detected" in resp_reuse.text.lower() or "revoked" in resp_reuse.text.lower()

        # Step 4: Now new_refresh_token_1 must ALSO be invalidated because the family was revoked!
        resp_family_blocked = await ac.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh_token_1})
        assert resp_family_blocked.status_code == 401
        assert "invalidated" in resp_family_blocked.text.lower() or "reuse detected" in resp_family_blocked.text.lower()

@pytest.mark.asyncio
async def test_h4_revoke_user_session_hash_matching(db_session):
    """
    H4: Fix revoke_user_session, which revokes hash(hash) and never matches.
    Verifies that calling revoke_user_session correctly invalidates the access token in get_current_user.
    """
    # Create test user
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    org = Organization(id=org_id, name="Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
    user = User(
        id=user_id,
        organization_id=org_id,
        email=email,
        hashed_password="hashed_pwd",
        full_name="Session User",
        role=UserRole.ADMIN,
        is_active=True
    )
    db_session.add(org)
    db_session.add(user)
    await db_session.commit()

    # Create access token and active session
    access_token = create_access_token({"sub": user.id, "org_id": org_id, "role": "admin", "is_login": True})
    token_hash = _hash_token(access_token)

    session_row = await create_user_session(
        db=db_session,
        user_id=user.id,
        org_id=org_id,
        access_token=access_token,
        ip_address="127.0.0.1",
        user_agent="TestAgent"
    )
    await db_session.commit()

    # Session exists and is not revoked
    assert session_row.session_token_hash == token_hash
    assert session_row.is_revoked is False

    # Revoke session via revoke_user_session
    success = await revoke_user_session(db=db_session, session_id=session_row.id, user_id=user.id)
    assert success is True
    await db_session.commit()

    # Re-fetch session to verify DB status
    stmt = select(UserSession).where(UserSession.id == session_row.id)
    res = await db_session.execute(stmt)
    updated_sess = res.scalar_one()
    assert updated_sess.is_revoked is True

    # Calling decode or get_current_user with the access token must now be rejected
    from unittest.mock import AsyncMock, MagicMock
    request = MagicMock()
    request.headers = {}
    credentials = MagicMock()
    credentials.credentials = access_token

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request=request, credentials=credentials, db=db_session)
    assert exc.value.status_code == 401
    assert "revoked" in exc.value.detail.lower()
