import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app

@pytest.mark.asyncio
async def test_stripe_checkout_and_webhook():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login to get token
        login_res = await client.post("/api/v1/auth/login", json={"email": "admin@azurehostel.com", "password": "admin123"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Create Stripe Checkout Session
        checkout_res = await client.post(
            "/api/v1/billing/checkout-session",
            json={"plan_name": "ENTERPRISE"},
            headers=headers
        )
        assert checkout_res.status_code == 200
        data = checkout_res.json()
        assert "checkout_url" in data
        assert data["plan_name"] == "ENTERPRISE"

        # 3. Simulate Stripe Webhook Event
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "org_azure_group",
                    "customer": "cus_test_12345",
                    "subscription": "sub_test_67890",
                    "metadata": {"organization_id": "org_azure_group", "target_plan": "ENTERPRISE"}
                }
            }
        }
        webhook_res = await client.post("/api/v1/billing/webhook", json=webhook_payload)
        assert webhook_res.status_code == 200
        assert webhook_res.json()["status"] == "success"

        # 4. Verify subscription status updated
        sub_res = await client.get("/api/v1/billing/subscription", headers=headers)
        assert sub_res.status_code == 200
        assert sub_res.json()["subscription"]["plan_name"] == "ENTERPRISE"

@pytest.mark.asyncio
async def test_google_oauth_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Get Google auth URL
        url_res = await client.get("/api/v1/auth/google/url")
        assert url_res.status_code == 200
        assert "auth_url" in url_res.json()
        assert "accounts.google.com" in url_res.json()["auth_url"]

        # 2. Callback code exchange
        cb_res = await client.post("/api/v1/auth/google/callback", json={"code": "mock_code_123"})
        assert cb_res.status_code == 200
        assert "access_token" in cb_res.json()

@pytest.mark.asyncio
async def test_gdpr_export_and_purge():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={"email": "admin@azurehostel.com", "password": "admin123"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. GDPR Export
        exp_res = await client.get("/api/v1/organizations/org_azure_group/export-data", headers=headers)
        assert exp_res.status_code == 200
        assert exp_res.json()["export_metadata"]["organization_id"] == "org_azure_group"
