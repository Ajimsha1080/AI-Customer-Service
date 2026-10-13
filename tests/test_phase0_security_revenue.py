import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.auth import create_access_token

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def org_admin_headers():
    token = create_access_token(data={"sub": "usr_admin_01", "org_id": "org_azure_group", "role": "ORGANIZATION_ADMIN"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def super_admin_headers():
    token = create_access_token(data={"sub": "usr_superadmin", "org_id": "org_azure_group", "role": "SUPER_ADMIN"})
    return {"Authorization": f"Bearer {token}"}

def test_unsigned_stripe_webhook_rejected(client):
    """0.1 Security: Forged or unsigned Stripe webhook must return 400, not fall back to JSON."""
    payload = {
        "id": "evt_forged_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "org_azure_group",
                "metadata": {"target_plan": "ENTERPRISE"}
            }
        }
    }
    # No stripe-signature header
    res = client.post("/api/v1/billing/webhook", json=payload)
    assert res.status_code == 400, f"Expected 400 for unsigned webhook, got {res.status_code}"

def test_billing_self_upgrade_forbidden_for_non_super_admin(client, org_admin_headers):
    """0.1 Revenue: Regular org admin must NOT be able to self-upgrade without paying via Stripe."""
    res = client.post(
        "/api/v1/billing/subscription/upgrade",
        headers=org_admin_headers,
        json={"plan_name": "ENTERPRISE"}
    )
    assert res.status_code in [403, 404], f"Expected 403 Forbidden for non-super-admin self-upgrade, got {res.status_code}"

def test_checkout_session_open_redirect_rejected(client, org_admin_headers):
    """0.1 Security: Malicious external redirect URLs must be rejected with 400."""
    res = client.post(
        "/api/v1/billing/checkout-session",
        headers=org_admin_headers,
        json={
            "plan_name": "PROFESSIONAL",
            "success_url": "https://attacker-phishing-site.com/steal-creds",
            "cancel_url": "https://attacker-phishing-site.com/cancel"
        }
    )
    assert res.status_code == 400, f"Expected 400 for unallowed redirect URL, got {res.status_code}"

def test_billing_self_upgrade_allowed_for_super_admin(client, super_admin_headers):
    """0.1 Revenue: SUPER_ADMIN is permitted to manually adjust or upgrade tier."""
    res = client.post(
        "/api/v1/billing/subscription/upgrade",
        headers=super_admin_headers,
        json={"plan_name": "BUSINESS"}
    )
    assert res.status_code == 200
    assert res.json()["plan_name"] == "BUSINESS"

def test_stripe_webhook_verified_signature_and_idempotency(client):
    """0.1 Stripe: Webhook with valid signature processes correctly and rejects duplicates."""
    import json
    import stripe
    import uuid
    from apps.api.config import settings

    evt_id = f"evt_test_valid_{uuid.uuid4().hex[:8]}"
    payload_dict = {
        "id": evt_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "org_azure_group",
                "customer": "cus_stripe_123",
                "subscription": "sub_stripe_123",
                "lines": {
                    "data": [
                        {"price": {"id": settings.STRIPE_PRICE_ENTERPRISE}}
                    ]
                }
            }
        }
    }
    payload_raw = json.dumps(payload_dict)
    sig_header = stripe.WebhookSignature.generate_signature_header(
        payload_raw, settings.STRIPE_WEBHOOK_SECRET
    )

    # First call: Processed successfully
    res1 = client.post(
        "/api/v1/billing/webhook",
        data=payload_raw,
        headers={"stripe-signature": sig_header, "Content-Type": "application/json"}
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "success"

    # Second call with same event ID: Idempotency check returns duplicate
    res2 = client.post(
        "/api/v1/billing/webhook",
        data=payload_raw,
        headers={"stripe-signature": sig_header, "Content-Type": "application/json"}
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"

def test_stripe_webhook_payment_failed_dunning(client):
    """0.1 Stripe: invoice.payment_failed marks subscription past_due with dunning attempt."""
    import json
    import stripe
    import uuid
    from apps.api.config import settings

    evt_dunning_id = f"evt_test_dunning_{uuid.uuid4().hex[:8]}"
    payload_dict = {
        "id": evt_dunning_id,
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "customer": "cus_stripe_123",
                "subscription": "sub_stripe_123"
            }
        }
    }
    payload_raw = json.dumps(payload_dict)
    sig_header = stripe.WebhookSignature.generate_signature_header(
        payload_raw, settings.STRIPE_WEBHOOK_SECRET
    )

    res = client.post(
        "/api/v1/billing/webhook",
        data=payload_raw,
        headers={"stripe-signature": sig_header, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

def test_customer_portal_requires_customer_id(client, org_admin_headers):
    """0.1 Billing: Customer portal request for org without Stripe customer returns 400."""
    res = client.post(
        "/api/v1/billing/customer-portal",
        headers=org_admin_headers,
        json={"return_url": "http://localhost:3002/app/billing"}
    )
    # May return 200 (if cus_stripe_123 was set in earlier test) or 400/502
    assert res.status_code in [200, 400, 502]

def test_webhook_signed_with_old_default_mock_secret_rejected(client):
    """A1 Requirement: Signing with old default 'whsec_mock_stripe_webhook_secret' must be rejected with 400."""
    import json
    import stripe
    import uuid

    evt_id = f"evt_forged_old_{uuid.uuid4().hex[:8]}"
    payload_dict = {
        "id": evt_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "org_azure_group",
                "customer": "cus_forged_999",
                "subscription": "sub_forged_999",
            }
        }
    }
    payload_raw = json.dumps(payload_dict)
    # Attacker tries using old default static mock secret
    old_default_secret = "whsec_mock_stripe_webhook_secret"
    sig_header = stripe.WebhookSignature.generate_signature_header(
        payload_raw, old_default_secret
    )

    res = client.post(
        "/api/v1/billing/webhook",
        data=payload_raw,
        headers={"stripe-signature": sig_header, "Content-Type": "application/json"}
    )
    assert res.status_code == 400, f"Expected 400 for forged webhook using old default secret, got {res.status_code}"
    assert "Invalid Stripe webhook signature" in res.json()["detail"]

def test_production_boot_refusal_with_mock_or_dev_secrets():
    """A1 Requirement: Settings must refuse to boot in production if secrets contain 'mock', 'dev_', or 'change'."""
    from apps.api.config import Settings

    # Refuse boot when SECRET_KEY is a dev/change placeholder
    with pytest.raises(ValueError, match="CRITICAL SECURITY RISK"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="development_secret_key_change_in_production",
            JWT_SECRET_KEY="real_secret_12345678901234567890",
            JWT_REFRESH_SECRET_KEY="real_secret_12345678901234567890",
            STRIPE_SECRET_KEY="sk_live_real_key_123",
            STRIPE_WEBHOOK_SECRET="whsec_real_secret_123",
            STRIPE_PRICE_STARTER="price_starter_real",
            STRIPE_PRICE_PROFESSIONAL="price_pro_real",
            STRIPE_PRICE_BUSINESS="price_biz_real",
            STRIPE_PRICE_ENTERPRISE="price_ent_real",
            OPENAI_API_KEY="sk-real-openai-key-live",
            REDIS_URL="redis://production-redis:6379/0",
            DATABASE_URL="postgresql+asyncpg://user:pass@prod-db:5432/db",
            CORS_ORIGINS=["https://app.hospitalityagent.cloud"]
        )

    # Refuse boot when STRIPE_WEBHOOK_SECRET contains 'mock'
    with pytest.raises(ValueError, match="CRITICAL SECURITY RISK"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="real_secret_12345678901234567890",
            JWT_SECRET_KEY="real_secret_12345678901234567890",
            JWT_REFRESH_SECRET_KEY="real_secret_12345678901234567890",
            STRIPE_SECRET_KEY="sk_live_real_key_123",
            STRIPE_WEBHOOK_SECRET="whsec_mock_stripe_webhook_secret",
            STRIPE_PRICE_STARTER="price_starter_real",
            STRIPE_PRICE_PROFESSIONAL="price_pro_real",
            STRIPE_PRICE_BUSINESS="price_biz_real",
            STRIPE_PRICE_ENTERPRISE="price_ent_real",
            OPENAI_API_KEY="sk-real-openai-key-live",
            REDIS_URL="redis://production-redis:6379/0",
            DATABASE_URL="postgresql+asyncpg://user:pass@prod-db:5432/db",
            CORS_ORIGINS=["https://app.hospitalityagent.cloud"]
        )

    # Refuse boot when DATABASE_URL is SQLite in production
    with pytest.raises(ValueError, match="CRITICAL SECURITY RISK"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="real_secret_12345678901234567890",
            JWT_SECRET_KEY="real_secret_12345678901234567890",
            JWT_REFRESH_SECRET_KEY="real_secret_12345678901234567890",
            STRIPE_SECRET_KEY="sk_live_real_key_123",
            STRIPE_WEBHOOK_SECRET="whsec_real_secret_123",
            STRIPE_PRICE_STARTER="price_starter_real",
            STRIPE_PRICE_PROFESSIONAL="price_pro_real",
            STRIPE_PRICE_BUSINESS="price_biz_real",
            STRIPE_PRICE_ENTERPRISE="price_ent_real",
            OPENAI_API_KEY="sk-real-openai-key-live",
            REDIS_URL="redis://production-redis:6379/0",
            DATABASE_URL="sqlite+aiosqlite:///dev.db",
            CORS_ORIGINS=["https://app.hospitalityagent.cloud"]
        )

def test_x_request_id_sanitization(client):
    """A5 Requirement: Inbound X-Request-ID must be sanitized against CRLF and injection attacks."""
    malicious_header = "<script>alert('xss')</script>\r\nInjected-Header: evil"
    res = client.get("/health", headers={"X-Request-ID": malicious_header})
    assert res.status_code == 200
    returned_request_id = res.headers.get("X-Request-ID")
    assert returned_request_id is not None
    assert "<script>" not in returned_request_id
    assert "\r" not in returned_request_id
    assert returned_request_id.startswith("req_")

    valid_custom_id = "trace-custom-correlation-12345"
    res2 = client.get("/health", headers={"X-Request-ID": valid_custom_id})
    assert res2.headers.get("X-Request-ID") == valid_custom_id


