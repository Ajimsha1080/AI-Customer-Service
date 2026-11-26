import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.config import Settings
from apps.api.auth import create_access_token, hash_password
from services.database.models import User, Organization, UserRole, UserSession, Subscription

def test_h11_production_enforces_cookie_secure():
    """H11: COOKIE_SECURE=True is strictly enforced in production."""
    with pytest.raises(ValueError) as exc:
        Settings(
            ENVIRONMENT="production",
            COOKIE_SECURE=False,
            KMS_PRIMARY_KEY_ID="arn:aws:kms:us-east-1:123456789012:key/test",
            SECRET_KEY="a" * 64,
            JWT_SECRET_KEY="b" * 64,
            JWT_REFRESH_SECRET_KEY="c" * 64,
            DATABASE_URL="postgresql+asyncpg://app_user:pwd@db:5432/hac",
            REDIS_URL="redis://redis:6379/0",
            STRIPE_SECRET_KEY="sk_live_12345",
            STRIPE_WEBHOOK_SECRET="whsec_12345",
            STRIPE_PRICE_STARTER="price_starter_live",
            STRIPE_PRICE_PROFESSIONAL="price_pro_live",
            STRIPE_PRICE_BUSINESS="price_biz_live",
            STRIPE_PRICE_ENTERPRISE="price_ent_live",
            OPENAI_API_KEY="sk-live-openai",
            WHATSAPP_APP_SECRET="d" * 32,
            WHATSAPP_VERIFY_TOKEN="e" * 16,
            WHATSAPP_API_KEY=None,
            CORS_ORIGINS=["https://app.concierge-ai.com"],
            EMAIL_SERVICE_PROVIDER="sendgrid",
            SENDGRID_API_KEY="SG.12345"
        )
    assert "COOKIE_SECURE must be True in production" in str(exc.value)

@pytest.mark.asyncio
async def test_h11_auth_cookies_and_csrf_token_issuance(db_session):
    """H11: Login sets httpOnly access/refresh tokens and double-submit csrf_token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Cookie Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        pwd = "CookiePassword123!"
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"cookie_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="Cookie User",
            hashed_password=hash_password(pwd),
            role=UserRole.STAFF,
            is_active=True,
            mfa_enabled=False
        )
        sub = Subscription(
            id=f"sub_{uuid.uuid4().hex[:8]}",
            organization_id=org_id,
            plan_name="ENTERPRISE",
            status="ACTIVE",
            subscription_status="active",
            max_agents=50,
            max_properties=20,
            max_conversations_per_month=50000
        )
        db_session.add(org)
        db_session.add(user)
        db_session.add(sub)
        await db_session.commit()

        login_res = await ac.post("/api/v1/auth/login", json={"email": user.email, "password": pwd})
        assert login_res.status_code == 200

        # Verify Cookies in response
        cookies = login_res.cookies
        assert "access_token" in cookies
        assert "refresh_token" in cookies
        assert "csrf_token" in cookies

@pytest.mark.asyncio
async def test_h11_csrf_double_submit_protection_on_mutating_requests(db_session):
    """H11: Cookie-authenticated mutating requests require matching X-CSRF-Token header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="CSRF Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"csrf_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="CSRF Admin",
            hashed_password=hash_password("password"),
            role=UserRole.ORGANIZATION_ADMIN,
            is_active=True
        )
        sub = Subscription(
            id=f"sub_{uuid.uuid4().hex[:8]}",
            organization_id=org_id,
            plan_name="ENTERPRISE",
            status="ACTIVE",
            subscription_status="active",
            max_agents=50,
            max_properties=20,
            max_conversations_per_month=50000
        )
        db_session.add(org)
        db_session.add(user)
        db_session.add(sub)
        await db_session.commit()

        token = create_access_token({"sub": user.id, "org_id": org_id, "role": "ORGANIZATION_ADMIN", "test_synthetic": True})
        csrf_secret = "csrf_token_value_random_12345"

        cookie_header = f"access_token={token}; csrf_token={csrf_secret}"

        # 1. Mutating POST without X-CSRF-Token header is rejected (403)
        no_csrf_res = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers={"Cookie": cookie_header},
            json={"email": "newbie@hotel.com", "role": "STAFF"}
        )
        assert no_csrf_res.status_code == 403
        assert "CSRF validation failed" in no_csrf_res.json()["detail"]

        # 2. Mutating POST with mismatched X-CSRF-Token is rejected (403)
        bad_csrf_res = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers={"Cookie": cookie_header, "X-CSRF-Token": "wrong_csrf_value"},
            json={"email": "newbie@hotel.com", "role": "STAFF"}
        )
        assert bad_csrf_res.status_code == 403
        assert "CSRF validation failed" in bad_csrf_res.json()["detail"]

        # 3. Mutating POST with matching X-CSRF-Token double-submit succeeds
        good_csrf_res = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers={"Cookie": cookie_header, "X-CSRF-Token": csrf_secret},
            json={"email": "newbie@hotel.com", "role": "STAFF"}
        )
        assert good_csrf_res.status_code == 200

        # 4. Bearer-authenticated request does not require CSRF token
        bearer_res = await ac.post(
            f"/api/v1/organizations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "newbie2@hotel.com", "role": "STAFF"}
        )
        assert bearer_res.status_code == 200
