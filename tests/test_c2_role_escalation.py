import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, AuditLog, Organization
from services.database.session import AsyncSessionLocal
from apps.api.routers.organizations import ALLOWED_TENANT_ASSIGNABLE_ROLES

@pytest.mark.asyncio
async def test_c2_role_escalation_rules(prepare_db):
    """Regression test for C2: privilege escalation protections in update_member_role."""
    transport = ASGITransport(app=app)
    async with AsyncSessionLocal() as db:
        # Create an ADMIN user and a STAFF user in org_azure_group for testing
        res_admin = await db.execute(select(User).where(User.id == "usr_test_admin"))
        admin_user = res_admin.scalar_one_or_none()
        if not admin_user:
            admin_user = User(
                id="usr_test_admin",
                organization_id="org_azure_group",
                email="test_admin@azurehostel.com",
                full_name="Test Admin",
                hashed_password="hashed_pw",
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
        else:
            admin_user.role = UserRole.ADMIN

        res_staff = await db.execute(select(User).where(User.id == "usr_test_staff"))
        staff_user = res_staff.scalar_one_or_none()
        if not staff_user:
            staff_user = User(
                id="usr_test_staff",
                organization_id="org_azure_group",
                email="test_staff@azurehostel.com",
                full_name="Test Staff",
                hashed_password="hashed_pw",
                role=UserRole.STAFF,
                is_active=True
            )
            db.add(staff_user)
        else:
            staff_user.role = UserRole.STAFF

        await db.commit()

    admin_token = create_access_token({
        "sub": "usr_test_admin",
        "email": "test_admin@azurehostel.com",
        "role": UserRole.ADMIN.value,
        "org_id": "org_azure_group"
    })
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unknown role -> 422
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_test_staff",
            json={"role": "SUPER_USER_UNKNOWN"},
            headers=headers
        )
        assert res.status_code == 422

        # 2. Assigning SUPER_ADMIN -> 422 (never in tenant allowlist)
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_test_staff",
            json={"role": "SUPER_ADMIN"},
            headers=headers
        )
        assert res.status_code == 422

        # 3. Caller cannot change their own role -> 403
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_test_admin",
            json={"role": "STAFF"},
            headers=headers
        )
        assert res.status_code == 403

        # 4. Caller cannot touch the OWNER -> 403
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_admin_01",  # usr_admin_01 is OWNER
            json={"role": "STAFF"},
            headers=headers
        )
        assert res.status_code == 403

        # 5. Caller may only assign roles strictly below their own (ADMIN cannot assign ADMIN) -> 403
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_test_staff",
            json={"role": "ADMIN"},
            headers=headers
        )
        assert res.status_code == 403

        # 6. Admin assigns VIEWER to STAFF (strictly below) -> 200
        res = await client.patch(
            "/api/v1/organizations/org_azure_group/members/usr_test_staff",
            json={"role": "VIEWER"},
            headers=headers
        )
        assert res.status_code == 200
        assert res.json()["role"] == "VIEWER"

    # 7. Audit log exists for the role change
    async with AsyncSessionLocal() as db:
        res_audit = await db.execute(
            select(AuditLog).where(
                AuditLog.action == "MEMBER_ROLE_UPDATED",
                AuditLog.target_id == "usr_test_staff"
            ).order_by(AuditLog.created_at.desc())
        )
        log_entry = res_audit.scalars().first()
        assert log_entry is not None
        assert log_entry.user_id == "usr_test_admin"
        assert log_entry.details_json.get("new_role") == "VIEWER"
