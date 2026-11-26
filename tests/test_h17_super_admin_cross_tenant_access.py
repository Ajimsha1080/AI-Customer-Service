import pytest
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password
from services.database.models import User, Organization, UserRole, UserSession

@pytest.mark.asyncio
async def test_h17_super_admin_cross_tenant_access_control_and_break_glass(db_session):
    """H17:
    - Super Admin cannot access customer tenant via ?organization_id without consent (403 CROSS_TENANT_ACCESS_DENIED).
    - Customer-consented impersonation grants access and is audited.
    - Two-person break-glass workflow enforces distinct requester and approver.
    - Customer can view all audit logs.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create Customer Tenant Org
        cust_org_id = str(uuid.uuid4())
        cust_org = Organization(
            id=cust_org_id,
            name="Customer Hotel",
            slug=f"cust-hotel-{uuid.uuid4().hex[:6]}",
            status="active"
        )
        db_session.add(cust_org)

        # Create Customer Owner User
        cust_user = User(
            id=str(uuid.uuid4()),
            organization_id=cust_org_id,
            email=f"owner_{uuid.uuid4().hex[:6]}@custhotel.com",
            full_name="Customer Owner",
            hashed_password=hash_password("password123"),
            role=UserRole.OWNER,
            is_active=True,
            email_verified=True
        )
        db_session.add(cust_user)

        # Create Platform Admin Org
        platform_org_id = str(uuid.uuid4())
        platform_org = Organization(
            id=platform_org_id,
            name="Platform Admin Org",
            slug=f"platform-{uuid.uuid4().hex[:6]}",
            status="active"
        )
        db_session.add(platform_org)

        # Create Super Admin 1
        sa1 = User(
            id=str(uuid.uuid4()),
            organization_id=platform_org_id,
            email=f"superadmin1_{uuid.uuid4().hex[:6]}@platform.com",
            full_name="Super Admin One",
            hashed_password=hash_password("password123"),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            email_verified=True
        )
        db_session.add(sa1)

        # Create Super Admin 2
        sa2 = User(
            id=str(uuid.uuid4()),
            organization_id=platform_org_id,
            email=f"superadmin2_{uuid.uuid4().hex[:6]}@platform.com",
            full_name="Super Admin Two",
            hashed_password=hash_password("password123"),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            email_verified=True
        )
        db_session.add(sa2)
        await db_session.commit()

        # Generate login tokens and sessions for Super Admins
        token_sa1 = create_access_token({"sub": sa1.id, "email": sa1.email, "role": "SUPER_ADMIN", "org_id": platform_org_id, "is_login": True})
        session_sa1 = UserSession(
            id=str(uuid.uuid4()),
            user_id=sa1.id,
            organization_id=platform_org_id,
            session_token_hash=hashlib.sha256(token_sa1.encode()).hexdigest(),
            device_name="Test Device",
            ip_address="127.0.0.1",
            user_agent="pytest",
            last_activity_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_revoked=False
        )
        db_session.add(session_sa1)

        token_sa2 = create_access_token({"sub": sa2.id, "email": sa2.email, "role": "SUPER_ADMIN", "org_id": platform_org_id, "is_login": True})
        session_sa2 = UserSession(
            id=str(uuid.uuid4()),
            user_id=sa2.id,
            organization_id=platform_org_id,
            session_token_hash=hashlib.sha256(token_sa2.encode()).hexdigest(),
            device_name="Test Device",
            ip_address="127.0.0.1",
            user_agent="pytest",
            last_activity_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_revoked=False
        )
        db_session.add(session_sa2)

        token_cust = create_access_token({"sub": cust_user.id, "email": cust_user.email, "role": "OWNER", "org_id": cust_org_id, "is_login": True})
        session_cust = UserSession(
            id=str(uuid.uuid4()),
            user_id=cust_user.id,
            organization_id=cust_org_id,
            session_token_hash=hashlib.sha256(token_cust.encode()).hexdigest(),
            device_name="Test Device",
            ip_address="127.0.0.1",
            user_agent="pytest",
            last_activity_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_revoked=False
        )
        db_session.add(session_cust)
        await db_session.commit()

        headers_sa1 = {"Authorization": f"Bearer {token_sa1}"}
        headers_sa2 = {"Authorization": f"Bearer {token_sa2}"}
        headers_cust = {"Authorization": f"Bearer {token_cust}"}

        # 1. Super Admin 1 attempts unconsented cross-tenant access -> 403 CROSS_TENANT_ACCESS_DENIED
        res_denied = await ac.get(f"/api/v1/organizations/{cust_org_id}", headers=headers_sa1)
        assert res_denied.status_code == 403
        assert "CROSS_TENANT_ACCESS_DENIED" in res_denied.json()["detail"]

        # 2. Consented Impersonation Flow
        # Customer grants support access for 2 hours
        cust_org.support_access_granted_until = datetime.now(timezone.utc) + timedelta(hours=2)
        cust_org.support_access_granted_by = cust_user.id
        await db_session.commit()

        # Super Admin 1 requests consented impersonation session
        res_impersonate = await ac.post(f"/api/v1/platform/support/impersonate/{cust_org_id}", headers=headers_sa1)
        assert res_impersonate.status_code == 200
        imp_token = res_impersonate.json()["impersonation_token"]

        # Access customer tenant with impersonation token -> 200 OK with X-Support-Impersonation header
        headers_imp = {"Authorization": f"Bearer {imp_token}"}
        res_imp_access = await ac.get(f"/api/v1/organizations/{cust_org_id}", headers=headers_imp)
        assert res_imp_access.status_code == 200
        assert res_imp_access.headers.get("X-Support-Impersonation") == "Active"

        # Revoke customer support access
        cust_org.support_access_granted_until = None
        await db_session.commit()

        # 3. Two-Person Break-Glass Flow
        # SA1 requests break-glass access
        res_bg_req = await ac.post(
            "/api/v1/platform/break-glass/request",
            headers=headers_sa1,
            json={"organization_id": cust_org_id, "reason": "Emergency outage investigation for payment system"}
        )
        assert res_bg_req.status_code == 200
        request_id = res_bg_req.json()["request_id"]
        assert res_bg_req.json()["status"] == "PENDING"

        # Requester SA1 tries to approve own request -> 403 Two-Person Rule Violation
        res_self_approve = await ac.post(f"/api/v1/platform/break-glass/approve/{request_id}", headers=headers_sa1)
        assert res_self_approve.status_code == 403
        assert "TWO_PERSON_RULE_VIOLATION" in res_self_approve.json()["detail"]

        # SA2 approves the request
        res_approve = await ac.post(f"/api/v1/platform/break-glass/approve/{request_id}", headers=headers_sa2)
        assert res_approve.status_code == 200
        assert res_approve.json()["status"] == "APPROVED"

        # Now SA1 can access customer tenant under the active break-glass session
        res_bg_access = await ac.get(f"/api/v1/organizations/{cust_org_id}", headers=headers_sa1)
        assert res_bg_access.status_code == 200
        assert res_bg_access.json()["id"] == cust_org_id

        # 4. Customer views their audit logs and sees all access records
        res_audit = await ac.get(f"/api/v1/organizations/{cust_org_id}/audit-logs", headers=headers_cust)
        assert res_audit.status_code == 200
        actions = [log["action"] for log in res_audit.json()]
        assert "BREAK_GLASS_REQUESTED" in actions
        assert "BREAK_GLASS_APPROVED" in actions
        assert "SUPPORT_IMPERSONATION_STARTED" in actions
