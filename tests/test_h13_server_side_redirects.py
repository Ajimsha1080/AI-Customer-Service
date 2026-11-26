import pytest
import uuid
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.config import settings
from apps.api.auth import create_access_token, hash_password
from services.database.models import User, Organization, UserRole, Subscription

@pytest.mark.asyncio
async def test_h13_google_oauth_redirect_uri_enforcement(db_session):
    """H13: Client-controlled redirect_uri in Google OAuth is rejected with 422; server-derived target is strictly used."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Mock Google client ID
        with patch.object(settings, "GOOGLE_CLIENT_ID", "mock-google-client-id"), \
             patch.object(settings, "GOOGLE_CLIENT_SECRET", "mock-google-client-secret"):

            # 1. Reject malicious user-supplied redirect_uri with 422
            res_evil = await ac.get("/api/v1/auth/google/url", params={"redirect_uri": "https://evil.com/callback"})
            assert res_evil.status_code == 422
            assert "User-controlled redirect_uri is forbidden" in res_evil.json()["detail"]

            # 2. Omitting redirect_uri builds strictly from FRONTEND_BASE_URL
            res_ok = await ac.get("/api/v1/auth/google/url")
            assert res_ok.status_code == 200
            data = res_ok.json()
            expected_redirect = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/auth/callback/google"
            assert expected_redirect in data["auth_url"]
            assert data["redirect_uri"] == expected_redirect

            # 3. Callback with malicious redirect_uri is rejected with 422 before any network call
            from apps.api.routers.auth import generate_oauth_state
            valid_state = generate_oauth_state()
            res_cb_evil = await ac.post("/api/v1/auth/google/callback", json={
                "code": "auth-code-123",
                "state": valid_state,
                "redirect_uri": "https://attacker.site/steal"
            })
            assert res_cb_evil.status_code == 422
            assert "User-controlled redirect_uri is forbidden" in res_cb_evil.json()["detail"]

@pytest.mark.asyncio
async def test_h13_stripe_billing_redirect_targets_enforcement(db_session):
    """H13: Stripe checkout and customer portal reject client-controlled URLs with 422 and enforce FRONTEND_BASE_URL."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Redirect Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"billing_red_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="Billing Redirect Admin",
            hashed_password=hash_password("password"),
            role=UserRole.ADMIN,
            is_active=True
        )
        sub = Subscription(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            plan_name="STARTER",
            stripe_customer_id="cus_test123",
            stripe_subscription_id="sub_test123",
            status="active"
        )
        db_session.add(org)
        db_session.add(user)
        db_session.add(sub)
        await db_session.commit()

        token = create_access_token({"sub": user.id, "org_id": org_id, "role": "ADMIN", "test_synthetic": True})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Checkout session with malicious success_url returns 422
        res_evil_success = await ac.post(
            "/api/v1/billing/checkout-session",
            headers=headers,
            json={"plan_name": "PROFESSIONAL", "success_url": "https://attacker.com/pwn"}
        )
        assert res_evil_success.status_code == 422
        assert "User-controlled success_url is forbidden" in res_evil_success.json()["detail"]

        # 2. Checkout session with malicious cancel_url returns 422
        res_evil_cancel = await ac.post(
            "/api/v1/billing/checkout-session",
            headers=headers,
            json={"plan_name": "PROFESSIONAL", "cancel_url": "https://attacker.com/pwn"}
        )
        assert res_evil_cancel.status_code == 422
        assert "User-controlled cancel_url is forbidden" in res_evil_cancel.json()["detail"]

        # 3. Customer portal with malicious return_url returns 422
        res_evil_portal = await ac.post(
            "/api/v1/billing/customer-portal",
            headers=headers,
            json={"return_url": "https://attacker.com/pwn"}
        )
        assert res_evil_portal.status_code == 422
        assert "User-controlled return_url is forbidden" in res_evil_portal.json()["detail"]

        # 4. Valid checkout session builds target URLs server-side from FRONTEND_BASE_URL
        with patch("services.billing.stripe_service.StripeBillingService.create_checkout_session_async") as mock_checkout:
            mock_checkout.return_value = {"checkout_url": "https://checkout.stripe.com/pay/cs_test"}
            res_valid = await ac.post(
                "/api/v1/billing/checkout-session",
                headers=headers,
                json={"plan_name": "PROFESSIONAL"}
            )
            assert res_valid.status_code == 200
            assert res_valid.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_test"
            mock_checkout.assert_called_once()
            _, kwargs = mock_checkout.call_args
            assert kwargs["success_url"] == f"{settings.FRONTEND_BASE_URL.rstrip('/')}/app/billing?session=success"
            assert kwargs["cancel_url"] == f"{settings.FRONTEND_BASE_URL.rstrip('/')}/app/billing?session=cancel"
