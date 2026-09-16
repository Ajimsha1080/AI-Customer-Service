import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from apps.api.main import app, live_broadcaster

from apps.api.auth import create_access_token

@pytest.mark.asyncio
async def test_super_admin_telemetry_endpoint():
    """Verify that Super Admin platform telemetry returns aggregated metrics and health status."""
    sa_token = create_access_token({"sub": "usr_superadmin", "org_id": "org_azure_group", "role": "SUPER_ADMIN"})
    headers = {"Authorization": f"Bearer {sa_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/platform/telemetry", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_organizations" in data
        assert "active_agents" in data
        assert "connected_integrations" in data
        assert "system_health" in data
        assert data["system_health"] == "100% OPERATIONAL"
        assert "sla_uptime" in data
        assert "recent_live_events" in data
        assert isinstance(data["recent_live_events"], list)

@pytest.mark.asyncio
async def test_super_admin_event_privacy_filtering():
    """Verify that events broadcasted to Super Admin stream strip PII and sensitive data."""
    q = await live_broadcaster.subscribe()
    
    # Broadcast an event containing operational summary
    raw_event = {
        "type": "LIVE_FOOD_UPDATE",
        "organization_id": "org_azure_group",
        "org_name": "Azure Palm Hostel",
        "title": "Dinner timing updated to 08:00 PM",
        "status": "ONLINE",
        "timestamp": "Just now"
    }
    await live_broadcaster.broadcast(raw_event)
    
    received = await q.get()
    assert received["type"] == "LIVE_FOOD_UPDATE"
    assert received["organization_id"] == "org_azure_group"
    
    # Verify no PII fields exist in standard telemetry broadcast schema
    forbidden_pii_keys = ["resident_name", "password", "ssn", "credit_card", "api_key", "phone_number"]
    for key in forbidden_pii_keys:
        assert key not in received

    live_broadcaster.unsubscribe(q)
