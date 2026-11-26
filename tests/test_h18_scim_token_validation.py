import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password
from services.database.models import User, Organization, UserRole, UserSession, SCIMToken

@pytest.mark.asyncio
async def test_h18_scim_bearer_token_argon2_and_revocation(db_session):
    """H18:
    - Reject unauthenticated requests to /Users and /Groups (401).
    - Arbitrary Bearer tokens fail authentication (401).
    - Tokens are hashed with Argon2 and bound to an org.
    - Expired tokens fail with 401.
    - Revoked tokens fail with 401.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create Test Org
        org_id = str(uuid.uuid4())
        org = Organization(
            id=org_id,
            name="SCIM Test Org",
            slug=f"scim-org-{uuid.uuid4().hex[:6]}",
            status="active"
        )
        db_session.add(org)

        # Create Admin User (Owner) to manage SCIM tokens
        admin_user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"scim_admin_{uuid.uuid4().hex[:6]}@scimtest.com",
            full_name="SCIM Admin",
            hashed_password=hash_password("password123"),
            role=UserRole.OWNER,
            is_active=True,
            email_verified=True
        )
        db_session.add(admin_user)
        await db_session.commit()

        # Admin login session
        admin_token = create_access_token({"sub": admin_user.id, "email": admin_user.email, "role": "OWNER", "org_id": org_id, "is_login": True})
        session = UserSession(
            id=str(uuid.uuid4()),
            user_id=admin_user.id,
            organization_id=org_id,
            session_token_hash="scim_admin_hash",
            device_name="Test Device",
            ip_address="127.0.0.1",
            user_agent="pytest",
            last_activity_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_revoked=False
        )
        import hashlib
        session.session_token_hash = hashlib.sha256(admin_token.encode()).hexdigest()
        db_session.add(session)
        await db_session.commit()

        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Reject unauthenticated request to /Users and /Groups
        res_no_auth_u = await ac.get("/api/v1/scim/v2/Users")
        assert res_no_auth_u.status_code == 401
        assert "SCIM Bearer token required" in res_no_auth_u.json()["detail"]

        res_no_auth_g = await ac.get("/api/v1/scim/v2/Groups")
        assert res_no_auth_g.status_code == 401
        assert "SCIM Bearer token required" in res_no_auth_g.json()["detail"]

        # 2. Arbitrary forged token rejected
        res_fake_token = await ac.get(
            "/api/v1/scim/v2/Users",
            headers={"Authorization": "Bearer forger_token_12345"}
        )
        assert res_fake_token.status_code == 401

        # 3. Create real Argon2 hashed SCIM token
        res_create = await ac.post(
            "/api/v1/scim/v2/tokens",
            headers=admin_headers,
            json={"name": "Okta Identity Provider Token", "expires_in_days": 30}
        )
        assert res_create.status_code == 200
        scim_raw_token = res_create.json()["token"]
        token_id = res_create.json()["id"]

        # Verify token in DB is Argon2 hashed (starts with $argon2)
        stmt = select(SCIMToken).where(SCIMToken.id == token_id)
        res_db = await db_session.execute(stmt)
        token_row = res_db.scalar_one()
        assert token_row.token_hash.startswith("$argon2")
        assert token_row.organization_id == org_id
        assert not token_row.is_revoked

        # 4. Access /Users and /Groups using valid SCIM Bearer token
        scim_headers = {"Authorization": f"Bearer {scim_raw_token}"}
        res_users = await ac.get("/api/v1/scim/v2/Users", headers=scim_headers)
        assert res_users.status_code == 200
        assert res_users.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]

        res_groups = await ac.get("/api/v1/scim/v2/Groups", headers=scim_headers)
        assert res_groups.status_code == 200
        assert len(res_groups.json()["Resources"]) > 0

        # 5. Revocation check: Admin revokes token
        res_revoke = await ac.delete(f"/api/v1/scim/v2/tokens/{token_id}", headers=admin_headers)
        assert res_revoke.status_code == 200

        # Subsequent call with revoked token -> 401
        res_after_revoke = await ac.get("/api/v1/scim/v2/Users", headers=scim_headers)
        assert res_after_revoke.status_code == 401
        assert "revoked" in res_after_revoke.json()["detail"].lower()

        # 6. Expiry check: Create expired token
        exp_token_id = str(uuid.uuid4())
        raw_exp_token = f"scim_{exp_token_id}_expiredsecret12345"
        exp_row = SCIMToken(
            id=exp_token_id,
            organization_id=org_id,
            name="Expired SCIM Token",
            token_hash=hash_password(raw_exp_token),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            is_revoked=False
        )
        db_session.add(exp_row)
        await db_session.commit()

        res_exp = await ac.get(
            "/api/v1/scim/v2/Users",
            headers={"Authorization": f"Bearer {raw_exp_token}"}
        )
        assert res_exp.status_code == 401
        assert "expired" in res_exp.json()["detail"].lower()
