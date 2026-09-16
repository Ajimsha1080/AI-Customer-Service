import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token

@pytest.mark.asyncio
async def test_unauthenticated_request_rejection():
    """Verify that protected API endpoints reject requests without a Bearer token with HTTP 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        endpoints = [
            ("GET", "/api/v1/auth/me"),
            ("GET", "/api/v1/organizations"),
            ("GET", "/api/v1/properties"),
            ("GET", "/api/v1/agents"),
            ("GET", "/api/v1/conversations"),
            ("GET", "/api/v1/knowledge/documents"),
            ("GET", "/api/v1/live-updates"),
            ("GET", "/api/v1/usage"),
            ("GET", "/api/v1/analytics"),
            ("GET", "/api/v1/platform/telemetry"),
        ]

        for method, url in endpoints:
            res = await ac.request(method, url)
            assert res.status_code == 401, f"Expected 401 Unauthorized for {method} {url}, got {res.status_code}"
            assert "detail" in res.json()

@pytest.mark.asyncio
async def test_cross_tenant_forbidden_enforcement():
    """Verify that Org Admin A cannot access or modify Org B's resources and receives HTTP 403."""
    import time
    ts = int(time.time()*1000)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Register Org A user
        reg_a = await ac.post("/api/v1/auth/register", json={
            "email": f"user_orga_{ts}@domain.com",
            "password": "Password123!",
            "full_name": "Org A Admin",
            "organization_name": f"Organization A {ts}",
            "organization_slug": f"org-a-slug-{ts}"
        })
        assert reg_a.status_code == 200
        token_a = reg_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # 2. Register Org B user
        reg_b = await ac.post("/api/v1/auth/register", json={
            "email": f"user_orgb_{ts}@domain.com",
            "password": "Password123!",
            "full_name": "Org B Admin",
            "organization_name": f"Organization B {ts}",
            "organization_slug": f"org-b-slug-{ts}"
        })
        assert reg_b.status_code == 200
        org_b_id = reg_b.json()["user"]["organization_id"]

        # 3. User A attempts to list properties belonging to Org B -> Expect HTTP 403 Forbidden
        res_cross = await ac.get(f"/api/v1/properties?organization_id={org_b_id}", headers=headers_a)
        assert res_cross.status_code == 403, f"Expected 403 Forbidden, got {res_cross.status_code}"
        assert "Access denied" in res_cross.json()["detail"]

        # 4. User A attempts to list agents belonging to Org B -> Expect HTTP 403 Forbidden
        res_agents = await ac.get(f"/api/v1/agents?organization_id={org_b_id}", headers=headers_a)
        assert res_agents.status_code == 403, f"Expected 403 Forbidden, got {res_agents.status_code}"

        # 5. User A attempts to access usage metrics of Org B -> Expect HTTP 403 Forbidden
        res_usage = await ac.get(f"/api/v1/usage?organization_id={org_b_id}", headers=headers_a)
        assert res_usage.status_code == 403

@pytest.mark.asyncio
async def test_staff_role_cannot_access_platform_endpoints():
    """Verify that STAFF or ORGANIZATION_ADMIN role tokens cannot access platform-only super admin endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "email": "admin@azurehostel.com",
            "password": "admin123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Attempt to access platform telemetry -> Expect HTTP 403 Forbidden
        res = await ac.get("/api/v1/platform/telemetry", headers=headers)
        assert res.status_code == 403
        assert "super admin privileges required" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_super_admin_cross_tenant_access():
    """Verify that Super Admin can access platform telemetry and multi-tenant control plane."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Login as Super Admin (seeded in lifespan)
        login_res = await ac.post("/api/v1/auth/login", json={
            "email": "superadmin@azurehostel.com",
            "password": "superadmin123"
        })
        assert login_res.status_code == 200
        sa_token = login_res.json()["access_token"]
        sa_headers = {"Authorization": f"Bearer {sa_token}"}

        # Super admin can fetch telemetry
        telem_res = await ac.get("/api/v1/platform/telemetry", headers=sa_headers)
        assert telem_res.status_code == 200
        assert telem_res.json()["system_health"] == "100% OPERATIONAL"

        # Super admin can list all organizations
        orgs_res = await ac.get("/api/v1/organizations", headers=sa_headers)
        assert orgs_res.status_code == 200
        assert isinstance(orgs_res.json(), list)
