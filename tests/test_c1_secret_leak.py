import os
import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import UserRole
import uuid

@pytest.mark.asyncio
async def test_c1_no_hardcoded_keys_in_frontend():
    """Verify that apps/web/src/app/platform/settings/page.tsx does not leak raw Sarvam API keys."""
    settings_page_path = os.path.join(os.getcwd(), "apps", "web", "src", "app", "platform", "settings", "page.tsx")
    assert os.path.exists(settings_page_path), "Platform settings page must exist"
    
    with open(settings_page_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Regression check: the leaked key must not be present
    assert "sk_hfcj1u2e_ZWj7CUgfsUhYTdOs7oHL22My" not in content
    # Nor should any raw unmasked key value be hardcoded in value attribute
    assert 'value="sk_' not in content

@pytest.mark.asyncio
async def test_c1_gitleaks_config_and_ci_blocking():
    """Verify .gitleaks.toml exists and CI Gitleaks step is blocking without continue-on-error."""
    gitleaks_toml = os.path.join(os.getcwd(), ".gitleaks.toml")
    assert os.path.exists(gitleaks_toml), ".gitleaks.toml must exist"
    
    ci_yml = os.path.join(os.getcwd(), ".github", "workflows", "ci.yml")
    with open(ci_yml, "r", encoding="utf-8") as f:
        ci_content = f.read()
    
    # Ensure Gitleaks step has no continue-on-error: true
    gitleaks_section = ci_content.split("Gitleaks Secret Scan")[1].split("Set up Python")[0]
    assert "continue-on-error: true" not in gitleaks_section

@pytest.mark.asyncio
async def test_c1_platform_settings_auth_and_masking():
    """Verify /api/v1/platform/settings enforces SUPER_ADMIN authorization and returns only masked values."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request -> 401
        res = await client.get("/api/v1/platform/settings")
        assert res.status_code == 401
        
        # 2. Regular tenant admin -> 403
        admin_token = create_access_token({
            "sub": "usr_admin_01",
            "email": "admin@azurehostel.com",
            "role": UserRole.OWNER.value,
            "org_id": "org_azure_group"
        })
        res_admin = await client.get(
            "/api/v1/platform/settings",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_admin.status_code == 403
        
        # 3. Super Admin -> 200 with masked strings
        super_token = create_access_token({
            "sub": "usr_superadmin",
            "email": "superadmin@azurehostel.com",
            "role": UserRole.SUPER_ADMIN.value,
            "org_id": "org_azure_group"
        })
        res_super = await client.get(
            "/api/v1/platform/settings",
            headers={"Authorization": f"Bearer {super_token}"}
        )
        assert res_super.status_code == 200
        data = res_super.json()
        assert "sarvam_api_key_masked" in data
        assert "openai_api_key_masked" in data
        assert "anthropic_api_key_masked" in data
        # Ensure no unmasked keys are returned
        for k, v in data.items():
            if "masked" in k:
                assert "sk_hfcj1u2e_ZWj7CUgfsUhYTdOs7oHL22My" not in str(v)
