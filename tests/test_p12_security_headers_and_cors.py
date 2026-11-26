import pytest
import re
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.config import settings

@pytest.mark.asyncio
async def test_p12_security_headers_presence_and_values():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health/live")
        assert res.status_code == 200

        headers = res.headers

        # 1. HSTS
        assert "Strict-Transport-Security" in headers
        hsts = headers["Strict-Transport-Security"]
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
        assert "preload" in hsts

        # 2. X-Content-Type-Options
        assert headers.get("X-Content-Type-Options") == "nosniff"

        # 3. X-Frame-Options
        assert headers.get("X-Frame-Options") == "DENY"

        # 4. Referrer-Policy
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

        # 5. Permissions-Policy
        perm = headers.get("Permissions-Policy", "")
        assert "camera=()" in perm
        assert "microphone=()" in perm
        assert "geolocation=()" in perm

        # 6. Content Security Policy with Nonce
        csp = headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self' 'nonce-" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

@pytest.mark.asyncio
async def test_p12_csp_nonce_is_unique_per_request():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get("/health/live")
        res2 = await client.get("/health/live")

        csp1 = res1.headers.get("Content-Security-Policy", "")
        csp2 = res2.headers.get("Content-Security-Policy", "")

        m1 = re.search(r"'nonce-([^']+)'", csp1)
        m2 = re.search(r"'nonce-([^']+)'", csp2)

        assert m1 is not None, "CSP must contain nonce in request 1"
        assert m2 is not None, "CSP must contain nonce in request 2"

        nonce1 = m1.group(1)
        nonce2 = m2.group(1)

        assert nonce1 != nonce2, "CSP nonce must be unique per request"
        assert len(nonce1) >= 16

@pytest.mark.asyncio
async def test_p12_cors_allowed_origin_receives_cors_headers():
    transport = ASGITransport(app=app)
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET"
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.options("/health/live", headers=headers)
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert res.headers.get("access-control-allow-credentials") == "true"

@pytest.mark.asyncio
async def test_p12_cors_unauthorized_origin_rejected():
    transport = ASGITransport(app=app)
    headers = {
        "Origin": "https://malicious-attacker.com",
        "Access-Control-Request-Method": "GET"
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.options("/health/live", headers=headers)
        # Unauthorized origin must NOT receive access-control-allow-origin header
        assert "access-control-allow-origin" not in res.headers

def test_p12_production_rejects_wildcard_cors(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://app_user:pass@10.0.0.1:5432/hac")
    monkeypatch.setattr(settings, "REDIS_URL", "rediss://:pass@10.0.0.2:6379/0")
    monkeypatch.setattr(settings, "EMAIL_SERVICE_PROVIDER", "ses")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "valid_secret_prod_123")
    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", "valid_verify_prod_123")
    monkeypatch.setattr(settings, "WHATSAPP_API_KEY", "valid_api_key_12345")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])

    with pytest.raises(ValueError) as exc_info:
        settings.validate_production_secrets()

    assert "CORS_ORIGINS must be explicitly configured in production without wildcards" in str(exc_info.value)
