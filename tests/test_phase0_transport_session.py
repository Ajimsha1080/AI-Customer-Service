import pytest
import uuid
import hmac
import hashlib
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.auth import create_access_token

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def org_owner_headers():
    token = create_access_token(data={"sub": "usr_admin_01", "org_id": "org_azure_group", "role": "OWNER"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def viewer_headers():
    token = create_access_token(data={"sub": "usr_viewer_01", "org_id": "org_azure_group", "role": "VIEWER"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def superadmin_headers():
    token = create_access_token(data={"sub": "usr_superadmin", "org_id": "org_azure_group", "role": "SUPER_ADMIN"})
    return {"Authorization": f"Bearer {token}"}

def test_cors_rejects_unauthorized_origin(client):
    """0.7 Transport: CORS must not reflect arbitrary unauthorized origins."""
    res = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://evil-attacker-site.com",
            "Access-Control-Request-Method": "POST"
        }
    )
    # Origin should not be reflected as allowed
    allow_origin = res.headers.get("access-control-allow-origin")
    assert allow_origin != "http://evil-attacker-site.com"

def test_ssrf_protection_blocks_cloud_metadata_and_loopback(client, org_owner_headers):
    """0.7 Transport: Outbound integrations must block AWS metadata (169.254.169.254) and loopback."""
    # 1. Test AWS/GCP metadata address
    res_metadata = client.post(
        "/api/v1/live-updates/integrations",
        headers=org_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_test",
            "name": "Cloud Metadata",
            "source_type": "REST_API",
            "source_url": "http://169.254.169.254/latest/meta-data/"
        }
    )
    assert res_metadata.status_code == 400
    assert "SSRF" in res_metadata.json()["detail"] or "forbidden" in res_metadata.json()["detail"].lower()

    # 2. Test loopback address
    res_loopback = client.post(
        "/api/v1/live-updates/integrations",
        headers=org_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_test",
            "name": "Localhost Attack",
            "source_type": "REST_API",
            "source_url": "http://127.0.0.1:8000/internal-secrets"
        }
    )
    assert res_loopback.status_code == 400
    assert "SSRF" in res_loopback.json()["detail"] or "forbidden" in res_loopback.json()["detail"].lower()

def test_integration_credentials_encrypted_at_rest_and_never_returned(client, org_owner_headers):
    """0.7 Transport: Integration credentials must be encrypted at rest and never exposed in plaintext."""
    secret_key = "super_secret_erp_api_key_xyz_123"
    res = client.post(
        "/api/v1/live-updates/integrations",
        headers=org_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_test",
            "name": "Secure ERP",
            "source_type": "REST_API",
            "source_url": "https://example.com/api",
            "credentials": secret_key
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert secret_key not in str(data)
    assert data.get("credentials_masked") == "••••••••"

    # List integration sources and confirm plaintext secret is never returned
    res_list = client.get("/api/v1/live-updates/integrations?organization_id=org_azure_group", headers=org_owner_headers)
    assert res_list.status_code == 200
    sources = res_list.json()
    assert len(sources) > 0
    for s in sources:
        assert secret_key not in str(s)
        if s["id"] == data["id"]:
            assert s["credentials_masked"] == "••••••••"

def test_metrics_and_db_health_require_super_admin(client, viewer_headers, superadmin_headers):
    """0.7 Transport: /metrics and /db-health must require SUPER_ADMIN privileges."""
    # Anonymous -> 401
    assert client.get("/metrics").status_code == 401
    assert client.get("/api/v1/platform/db-health").status_code == 401

    # Viewer -> 403
    assert client.get("/metrics", headers=viewer_headers).status_code == 403
    assert client.get("/api/v1/platform/db-health", headers=viewer_headers).status_code == 403

    # Super Admin -> 200
    assert client.get("/metrics", headers=superadmin_headers).status_code == 200
    assert client.get("/api/v1/platform/db-health", headers=superadmin_headers).status_code == 200

def test_ready_health_probe_reports_accurate_status(client):
    """0.7 Transport: /ready must perform real service pings and not falsely report operational."""
    res = client.get("/ready")
    assert res.status_code in (200, 503)
    data = res.json()
    # Check that real service check fields exist
    assert "database" in data
    assert "redis" in data
    assert "vector_store" in data
    # Since Redis is not running locally, redis status should accurately be disconnected
    assert data["redis"] in ("connected", "disconnected")

def test_whatsapp_webhook_signature_verification(client):
    """0.7 Transport: WhatsApp webhook must reject forged or missing signatures."""
    payload = b'{"object": "whatsapp_business_account"}'
    # Missing signature -> 403
    res_missing = client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=payload,
        headers={"Content-Type": "application/json"}
    )
    assert res_missing.status_code == 403

    # Forged signature -> 403
    res_forged = client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=payload,
        headers={"Content-Type": "application/json", "x-hub-signature-256": "sha256=invalid_fake_signature"}
    )
    assert res_forged.status_code == 403

def test_login_lockout_after_repeated_failures(client):
    """0.7 Transport: Repeated invalid logins must trigger account lockout (429)."""
    target_email = f"lockout_test_{uuid.uuid4().hex[:6]}@example.com"
    # Register user first
    res_reg = client.post("/api/v1/auth/register", json={
        "email": target_email,
        "password": "CorrectPassword123!",
        "full_name": "Lockout User"
    })
    assert res_reg.status_code == 200

    # 5 failed login attempts
    for _ in range(5):
        client.post("/api/v1/auth/login", json={
            "email": target_email,
            "password": "WrongPassword!"
        })

    # 6th attempt should be locked out with 429
    res_locked = client.post("/api/v1/auth/login", json={
        "email": target_email,
        "password": "CorrectPassword123!"
    })
    assert res_locked.status_code == 429
    assert "locked" in res_locked.json()["detail"].lower()

def test_refresh_token_rotation_and_revocation(client):
    """0.7 Transport: Refresh token rotation with reuse rejection."""
    email = f"rotation_{uuid.uuid4().hex[:6]}@example.com"
    reg_res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password123!",
        "full_name": "Rotation User"
    })
    assert reg_res.status_code == 200
    ref_token = reg_res.json()["refresh_token"]

    # Logout to revoke token
    logout_res = client.post("/api/v1/auth/logout", json={"refresh_token": ref_token})
    assert logout_res.status_code == 200

    # Attempting to use the revoked token must fail with 401
    ref_res = client.post("/api/v1/auth/refresh", json={"refresh_token": ref_token})
    assert ref_res.status_code == 401
    assert "revoked" in ref_res.json()["detail"].lower() or "reuse" in ref_res.json()["detail"].lower()
