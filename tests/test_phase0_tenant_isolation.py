import pytest
import uuid
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.auth import create_access_token

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def org_a_owner_headers():
    token = create_access_token(data={"sub": "usr_admin_01", "org_id": "org_azure_group", "role": "OWNER"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def org_b_owner_headers(client):
    # Register Org B
    email = f"org_b_{uuid.uuid4().hex[:6]}@example.com"
    res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password123!",
        "full_name": "Org B Owner",
        "organization_name": "Org B Resort"
    })
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_unknown_agent_returns_404(client, org_a_owner_headers):
    """0.4 Tenant Isolation: Unknown agent must return 404, not fallback."""
    res = client.get("/api/v1/agents/agt_non_existent_999", headers=org_a_owner_headers)
    assert res.status_code == 404

    res_chat = client.post(
        "/api/v1/agents/agt_non_existent_999/chat",
        json={"organization_id": "org_azure_group", "property_id": "prop_test", "message": "Hello"}
    )
    assert res_chat.status_code == 404

def test_org_b_cannot_pause_or_deploy_org_a_agent(client, org_a_owner_headers, org_b_owner_headers):
    """0.4 Tenant Isolation: Org B cannot deploy, pause, or disable Org A's agent."""
    # 1. First create a property and agent in Org A
    res_prop = client.post(
        "/api/v1/properties",
        headers=org_a_owner_headers,
        json={"organization_id": "org_azure_group", "name": "Org A Beach Villa"}
    )
    assert res_prop.status_code == 200
    prop_id = res_prop.json()["id"]

    res_agent = client.post(
        "/api/v1/agents",
        headers=org_a_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": prop_id,
            "name": "Org A Concierge",
            "agent_type": "CONCIERGE"
        }
    )
    assert res_agent.status_code == 200
    agent_id = res_agent.json()["id"]

    # 2. Org B attempts to pause Org A's agent
    res_pause = client.post(f"/api/v1/agents/{agent_id}/pause", headers=org_b_owner_headers)
    assert res_pause.status_code in [403, 404], f"Org B must not pause Org A agent! Got {res_pause.status_code}"

    # Org B attempts to deploy Org A's agent
    res_deploy = client.post(f"/api/v1/agents/{agent_id}/deploy", headers=org_b_owner_headers)
    assert res_deploy.status_code in [403, 404], f"Org B must not deploy Org A agent! Got {res_deploy.status_code}"

def test_invalid_agent_type_returns_400(client, org_a_owner_headers):
    """0.4 Validation: Invalid agent_type must return 400 Bad Request, not 500 error."""
    res = client.post(
        "/api/v1/agents",
        headers=org_a_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_123",
            "name": "Broken Agent",
            "agent_type": "INVALID_EXPLODING_TYPE"
        }
    )
    assert res.status_code == 400

def test_empty_agent_list_returns_empty_array(client, org_b_owner_headers):
    """0.4 Data integrity: Org with zero agents must return [] instead of hardcoded 'agt_hostel_01'."""
    res = client.get("/api/v1/agents", headers=org_b_owner_headers)
    assert res.status_code == 200
    assert res.json() == []

def test_create_organization_restricted_to_super_admin(client, org_a_owner_headers):
    """0.4 Route hardening: Non-super-admin cannot create arbitrary organizations."""
    res = client.post(
        "/api/v1/organizations",
        headers=org_a_owner_headers,
        json={"name": "Attacker Org", "slug": "attacker-org"}
    )
    assert res.status_code == 403

def test_takeover_foreign_conversation_returns_404(client, org_b_owner_headers):
    """0.4 Route hardening: Takeover on non-existent or foreign conversation returns 404."""
    res = client.post(
        "/api/v1/conversations/conv_foreign_999/takeover",
        headers=org_b_owner_headers,
        json={"reason": "Attempt takeover"}
    )
    assert res.status_code == 404
