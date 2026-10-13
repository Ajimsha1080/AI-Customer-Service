import pytest
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, Organization, Property
from services.operations.localization import localization_service

client = TestClient(app)

def _get_owner_headers(org_id: str = "org_azure_group"):
    token = create_access_token(data={
        "sub": "usr_admin_01",
        "role": UserRole.OWNER.value,
        "organization_id": org_id
    })
    return {"Authorization": f"Bearer {token}"}

def test_hospitality_multi_currency_converter():
    """F8.1 Multi-currency conversion: USD, EUR, GBP, INR, JPY, AED."""
    # USD to EUR
    eur_val = localization_service.convert_currency(100.0, "USD", "EUR")
    assert eur_val == 92.0

    # EUR to USD
    usd_val = localization_service.convert_currency(92.0, "EUR", "USD")
    assert usd_val == 100.0

    # USD to INR
    inr_val = localization_service.convert_currency(100.0, "USD", "INR")
    assert inr_val == 8350.0

    # USD to AED
    aed_val = localization_service.convert_currency(100.0, "USD", "AED")
    assert aed_val == 367.0

    # Unsupported currency raises ValueError
    with pytest.raises(ValueError):
        localization_service.convert_currency(100.0, "USD", "XYZ")


def test_property_timezone_formatting_and_rtl_detection():
    """F8.2 Property timezone localization and RTL language detection."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Dubai is UTC+4
    dubai_str = localization_service.format_property_time(dt, "Asia/Dubai")
    assert "+04:00" in dubai_str
    assert "16:00:00" in dubai_str

    # New York is UTC-4 (EDT in June)
    ny_str = localization_service.format_property_time(dt, "America/New_York")
    assert "-04:00" in ny_str
    assert "08:00:00" in ny_str

    # RTL Detection
    assert localization_service.is_rtl_language("ar") is True
    assert localization_service.is_rtl_language("ar-SA") is True
    assert localization_service.is_rtl_language("he") is True
    assert localization_service.is_rtl_language("en") is False
    assert localization_service.is_rtl_language("fr") is False


@pytest.mark.asyncio
async def test_tenant_offboarding_export_bundle_and_checksum(db_session):
    """F8.3 Complete tenant offboarding export bundle (JSON/CSV) with SHA-256 integrity checksum."""
    headers = _get_owner_headers("org_azure_group")

    # Request export bundle for org_azure_group
    res = client.post("/api/v1/compliance/organizations/org_azure_group/export-bundle", headers=headers)
    assert res.status_code == 200
    bundle = res.json()

    assert bundle["export_metadata"]["organization_id"] == "org_azure_group"
    assert "sha256_checksum" in bundle["export_metadata"]
    assert len(bundle["export_metadata"]["sha256_checksum"]) == 64

    # Verify counts structure
    assert "counts" in bundle
    assert "properties" in bundle["counts"]
    assert "agents" in bundle["counts"]
    assert "conversations" in bundle["counts"]

    # Verify cross-tenant isolation: cannot export another tenant's bundle
    cross_res = client.post("/api/v1/compliance/organizations/org_other_tenant/export-bundle", headers=headers)
    assert cross_res.status_code == 403
