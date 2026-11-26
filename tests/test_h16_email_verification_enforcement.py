import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password, create_special_token
from services.database.models import User, Organization, UserRole, Subscription

@pytest.mark.asyncio
async def test_h16_login_grace_window_and_expired_verification(db_session):
    """H16: Login is permitted within grace window; unverified user outside grace window is blocked with 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Verify Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        db_session.add(org)

        # 1. Recent unverified user (within 24h grace window) can log in
        recent_email = f"recent_unverified_{uuid.uuid4().hex[:6]}@hotel.com"
        user_recent = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=recent_email,
            full_name="Recent User",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=False,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        db_session.add(user_recent)

        # 2. Expired unverified user (>24h old) is blocked
        expired_email = f"expired_unverified_{uuid.uuid4().hex[:6]}@hotel.com"
        user_expired = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=expired_email,
            full_name="Expired User",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=False,
            created_at=datetime.now(timezone.utc) - timedelta(hours=48)
        )
        db_session.add(user_expired)
        await db_session.commit()

        # Login recent -> succeeds (200)
        res_recent = await ac.post("/api/v1/auth/login", json={"email": recent_email, "password": "password123"})
        assert res_recent.status_code == 200
        assert "access_token" in res_recent.json()

        # Login expired -> 403 Forbidden
        res_expired = await ac.post("/api/v1/auth/login", json={"email": expired_email, "password": "password123"})
        assert res_expired.status_code == 403
        assert "EMAIL_NOT_VERIFIED" in res_expired.json()["detail"]

        # Resend verification
        res_resend = await ac.post("/api/v1/auth/resend-verification", json={"email": expired_email})
        assert res_resend.status_code == 200

        # Verify email using verification token
        verify_token = create_special_token(
            token_type="email_verify",
            aud="email_verify",
            data={"sub": user_expired.id, "email": expired_email, "scope": "email_verification"},
            expires_delta=timedelta(hours=24)
        )
        res_verify = await ac.post("/api/v1/auth/verify-email", json={"token": verify_token})
        assert res_verify.status_code == 200

        # Login now succeeds after verification
        res_login_after = await ac.post("/api/v1/auth/login", json={"email": expired_email, "password": "password123"})
        assert res_login_after.status_code == 200

@pytest.mark.asyncio
async def test_h16_invites_and_billing_blocked_for_unverified_user(db_session):
    """H16: Inviting new members and modifying billing require email verification."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Billing Invite Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        sub = Subscription(id=str(uuid.uuid4()), organization_id=org_id, plan_name="ENTERPRISE", status="active")
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"admin_unverified_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="Unverified Admin",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=False
        )
        db_session.add(org)
        db_session.add(sub)
        db_session.add(user)
        await db_session.commit()

        token = create_access_token({"sub": user.id, "org_id": org_id, "role": "ADMIN", "test_synthetic": True})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Invite blocked for unverified user
        res_inv = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers=headers,
            json={"email": "newbie@hotel.com", "role": "STAFF"}
        )
        assert res_inv.status_code == 403
        assert "EMAIL_NOT_VERIFIED" in res_inv.json()["detail"]

        # 2. Billing checkout session blocked for unverified user
        res_bill = await ac.post(
            "/api/v1/billing/checkout-session",
            headers=headers,
            json={"plan_name": "PROFESSIONAL"}
        )
        assert res_bill.status_code == 403
        assert "EMAIL_NOT_VERIFIED" in res_bill.json()["detail"]

        # 3. Customer portal blocked for unverified user
        res_portal = await ac.post(
            "/api/v1/billing/customer-portal",
            headers=headers,
            json={}
        )
        assert res_portal.status_code == 403
        assert "EMAIL_NOT_VERIFIED" in res_portal.json()["detail"]

        # 4. Once verified, invitations and billing are unblocked
        user.email_verified = True
        await db_session.commit()

        res_inv_ok = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers=headers,
            json={"email": "newbie@hotel.com", "role": "STAFF"}
        )
        assert res_inv_ok.status_code == 200
        assert "invitation_token" in res_inv_ok.json()
