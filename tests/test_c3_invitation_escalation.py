import pytest
import secrets
from datetime import datetime, timezone, timedelta
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, Invitation, Organization
from services.database.session import AsyncSessionLocal

@pytest.mark.asyncio
async def test_c3_invitation_escalation_rules(prepare_db):
    """Regression test for C3: privilege escalation checks on invitation creation and acceptance."""
    transport = ASGITransport(app=app)
    
    # Setup test inviter admin
    async with AsyncSessionLocal() as db:
        res_admin = await db.execute(select(User).where(User.id == "usr_inv_admin"))
        inv_admin = res_admin.scalar_one_or_none()
        if not inv_admin:
            inv_admin = User(
                id="usr_inv_admin",
                organization_id="org_azure_group",
                email="inv_admin@azurehostel.com",
                full_name="Invitation Admin",
                hashed_password="hashed_pw",
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(inv_admin)
        else:
            inv_admin.role = UserRole.ADMIN
        await db.commit()

    admin_token = create_access_token({
        "sub": "usr_inv_admin",
        "email": "inv_admin@azurehostel.com",
        "role": UserRole.ADMIN.value,
        "org_id": "org_azure_group"
    })
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unknown role -> 422
        res = await client.post(
            "/api/v1/organizations/org_azure_group/invitations",
            json={"email": "guest1@example.com", "role": "SUPER_TENANT"},
            headers=headers
        )
        assert res.status_code == 422

        # 2. SUPER_ADMIN invitation -> 422
        res = await client.post(
            "/api/v1/organizations/org_azure_group/invitations",
            json={"email": "guest2@example.com", "role": "SUPER_ADMIN"},
            headers=headers
        )
        assert res.status_code == 422

        # 3. OWNER invitation -> 422
        res = await client.post(
            "/api/v1/organizations/org_azure_group/invitations",
            json={"email": "guest3@example.com", "role": "OWNER"},
            headers=headers
        )
        assert res.status_code == 422

        # 4. Caller inviting role equal to caller (ADMIN -> ADMIN) -> 403
        res = await client.post(
            "/api/v1/organizations/org_azure_group/invitations",
            json={"email": "guest4@example.com", "role": "ADMIN"},
            headers=headers
        )
        assert res.status_code == 403

        # 5. Caller inviting strictly below caller (ADMIN -> STAFF) -> 200
        res = await client.post(
            "/api/v1/organizations/org_azure_group/invitations",
            json={"email": "valid_staff@example.com", "role": "STAFF"},
            headers=headers
        )
        assert res.status_code == 200

    # 6. Test acceptance re-checks
    async with AsyncSessionLocal() as db:
        # Create an illegal invitation with SUPER_ADMIN
        illegal_token = secrets.token_urlsafe(32)
        inv_illegal = Invitation(
            id=str(uuid.uuid4()),
            organization_id="org_azure_group",
            email="tampered@example.com",
            role="SUPER_ADMIN",
            token=illegal_token,
            invited_by_user_id="usr_inv_admin",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            created_at=datetime.now(timezone.utc)
        )
        db.add(inv_illegal)

        # Create an invitation where inviter was demoted to STAFF after creating STAFF invite
        demoted_token = secrets.token_urlsafe(32)
        inv_demoted = Invitation(
            id=str(uuid.uuid4()),
            organization_id="org_azure_group",
            email="demoted_inviter@example.com",
            role="STAFF",
            token=demoted_token,
            invited_by_user_id="usr_inv_admin",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            created_at=datetime.now(timezone.utc)
        )
        db.add(inv_demoted)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Accepting illegal SUPER_ADMIN token -> 422
        res = await client.post(
            "/api/v1/auth/accept-invitation",
            json={
                "invitation_token": illegal_token,
                "full_name": "Tampered User",
                "password": "Password123!@#"
            }
        )
        assert res.status_code == 422

        # Demote the inviter to STAFF (now equal to STAFF invite)
        async with AsyncSessionLocal() as db:
            res_admin = await db.execute(select(User).where(User.id == "usr_inv_admin"))
            inv_admin = res_admin.scalar_one_or_none()
            inv_admin.role = UserRole.STAFF
            await db.commit()

        # Accepting when inviter is no longer strictly higher than invite role -> 403
        res = await client.post(
            "/api/v1/auth/accept-invitation",
            json={
                "invitation_token": demoted_token,
                "full_name": "Demoted Target",
                "password": "Password123!@#"
            }
        )
        assert res.status_code == 403
