import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from apps.api.config import settings
from apps.api.auth import (
    hash_password, create_access_token, create_user_session, _hash_token
)
from services.database.models import User, Organization, UserRole, UserSession, AuditLog
from services.database.session import AsyncSessionLocal

@pytest.mark.asyncio
async def test_h2_session_enforcement_and_impersonation_audit(prepare_db):
    """
    H2 Regression Tests:
    1. get_current_user requires a valid UserSession row for login tokens; missing row returns 401.
    2. Revoked session (is_revoked=True) returns 401.
    3. Expired session (expires_at < now) returns 401.
    4. Inactive session (> 60 min idle timeout) returns 401.
    5. In production environment (ENVIRONMENT='production'), all synthetic tokens without a UserSession are rejected.
    6. Impersonation gets its own UserSession row (max 60 minutes) and every impersonated request is audited in audit_logs.
    """
    transport = ASGITransport(app=app)
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4().hex[:6]
    org_id = f"org_h2_{uid}"
    user_id = f"usr_h2_{uid}"
    sa_id = f"usr_h2_sa_{uid}"

    async with AsyncSessionLocal() as db:
        test_org = Organization(
            id=org_id,
            name="H2 Test Org",
            slug=f"h2-test-org-{uid}",
            support_access_granted_until=now + timedelta(hours=2)
        )
        test_user = User(
            id=user_id,
            organization_id=org_id,
            email=f"member_{uid}@h2test.com",
            full_name="H2 Member",
            hashed_password=hash_password("Pass123!"),
            role=UserRole.ADMIN,
            is_active=True
        )
        super_admin = User(
            id=sa_id,
            organization_id="org_azure_group",
            email=f"superadmin_{uid}@platform.com",
            full_name="Platform Super Admin",
            hashed_password=hash_password("SuperSecret123!"),
            role=UserRole.SUPER_ADMIN,
            is_active=True
        )
        db.add_all([test_org, test_user, super_admin])
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login token with no UserSession row in DB -> MUST BE 401
        orphan_token = create_access_token({
            "sub": user_id,
            "org_id": org_id,
            "role": "ADMIN",
            "is_login": True
        })
        res_orphan = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {orphan_token}"})
        assert res_orphan.status_code == 401, f"Expected 401 for orphan login token, got {res_orphan.status_code}"
        assert "session" in res_orphan.json()["detail"].lower()

        # 2. Valid token with active UserSession -> 200
        valid_token = create_access_token({
            "sub": user_id,
            "org_id": org_id,
            "role": "ADMIN",
            "is_login": True
        })
        async with AsyncSessionLocal() as db:
            sess_valid = await create_user_session(
                db=db,
                user_id=user_id,
                org_id=org_id,
                access_token=valid_token
            )
            await db.commit()

        res_valid = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
        assert res_valid.status_code == 200, res_valid.text

        # 3. Revoked UserSession -> 401
        revoked_token = create_access_token({
            "sub": user_id,
            "org_id": org_id,
            "role": "ADMIN",
            "is_login": True
        })
        async with AsyncSessionLocal() as db:
            sess_revoked = await create_user_session(
                db=db,
                user_id=user_id,
                org_id=org_id,
                access_token=revoked_token
            )
            sess_revoked.is_revoked = True
            await db.commit()

        res_revoked = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {revoked_token}"})
        assert res_revoked.status_code == 401
        assert "revoked" in res_revoked.json()["detail"].lower()

        # 4. Expired UserSession (absolute timeout) -> 401
        expired_token = create_access_token({
            "sub": user_id,
            "org_id": org_id,
            "role": "ADMIN",
            "is_login": True
        })
        async with AsyncSessionLocal() as db:
            sess_expired = await create_user_session(
                db=db,
                user_id=user_id,
                org_id=org_id,
                access_token=expired_token
            )
            sess_expired.expires_at = now - timedelta(minutes=5)
            await db.commit()

        res_expired = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert res_expired.status_code == 401
        assert "expired" in res_expired.json()["detail"].lower()

        # 5. Idle UserSession (> 60 minutes inactivity) -> 401
        idle_token = create_access_token({
            "sub": user_id,
            "org_id": org_id,
            "role": "ADMIN",
            "is_login": True
        })
        async with AsyncSessionLocal() as db:
            sess_idle = await create_user_session(
                db=db,
                user_id=user_id,
                org_id=org_id,
                access_token=idle_token
            )
            sess_idle.last_activity_at = now - timedelta(minutes=65)
            await db.commit()

        res_idle = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {idle_token}"})
        assert res_idle.status_code == 401
        assert "inactivity" in res_idle.json()["detail"].lower()

        # 6. Production mode enforcement: even synthetic test tokens fail without UserSession
        orig_env = settings.ENVIRONMENT
        try:
            settings.ENVIRONMENT = "production"
            raw_token = create_access_token({"sub": user_id, "org_id": org_id, "role": "ADMIN"})
            res_prod = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
            assert res_prod.status_code == 401, f"Expected 401 in production for token without session, got {res_prod.status_code}"
        finally:
            settings.ENVIRONMENT = orig_env

        # 7. Impersonation Session Creation & Audit Logging
        sa_token = create_access_token({
            "sub": sa_id,
            "org_id": "org_azure_group",
            "role": "SUPER_ADMIN",
            "is_login": True
        })
        async with AsyncSessionLocal() as db:
            await create_user_session(
                db=db,
                user_id=sa_id,
                org_id="org_azure_group",
                access_token=sa_token
            )
            await db.commit()

        # Call impersonate endpoint
        imp_resp = await client.post(
            f"/api/v1/platform/support/impersonate/{org_id}",
            headers={"Authorization": f"Bearer {sa_token}"}
        )
        assert imp_resp.status_code == 200, imp_resp.text
        imp_data = imp_resp.json()
        imp_token = imp_data["impersonation_token"]

        # Verify a UserSession row was created for the impersonation token, capped at 60 mins
        imp_token_hash = _hash_token(imp_token)
        async with AsyncSessionLocal() as db:
            stmt = select(UserSession).where(UserSession.session_token_hash == imp_token_hash)
            res = await db.execute(stmt)
            imp_sess = res.scalar_one_or_none()
            assert imp_sess is not None
            assert imp_sess.user_id == sa_id
            assert imp_sess.organization_id == org_id
            # Session expiry must not exceed 60 minutes from now
            exp_tz = imp_sess.expires_at.replace(tzinfo=timezone.utc) if imp_sess.expires_at.tzinfo is None else imp_sess.expires_at
            assert exp_tz <= now + timedelta(minutes=61)

        # Make an authenticated request using the impersonation token
        imp_req = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {imp_token}"}
        )
        assert imp_req.status_code == 200

        # Verify an audit log row was recorded for the impersonated request
        async with AsyncSessionLocal() as db:
            audit_stmt = select(AuditLog).where(
                AuditLog.action == "SUPPORT_IMPERSONATED_REQUEST",
                AuditLog.organization_id == org_id
            )
            audit_res = await db.execute(audit_stmt)
            audit_row = audit_res.scalar_one_or_none()
            assert audit_row is not None
            assert audit_row.user_id == sa_id
            assert audit_row.target_id == "GET /api/v1/auth/me"
