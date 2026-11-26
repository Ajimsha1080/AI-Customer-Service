import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from services.database.models import Agent, AgentStatus, AgentConfig, Organization, Property
from services.database.session import AsyncSessionLocal
import uuid

@pytest.mark.asyncio
async def test_public_agent_endpoint_and_chat_flow(prepare_db):
    """
    F1 Security & Correctness Verification:
    1. GET /api/v1/public/agents/{id} returns 200 with greeting, display_name, languages, and branding for ACTIVE agents without auth.
    2. GET /api/v1/public/agents/{id} returns 404 for non-existent or inactive agents.
    3. POST /api/v1/agents/{id}/chat works without client-supplied organization_id or property_id.
    4. Chat returns conversation_id and signed guest_token.
    5. Second turn with conversation_id and guest_token continues in the same conversation.
    6. Chat to non-ACTIVE agent returns 400.
    """
    async with AsyncSessionLocal() as db:
        test_org = Organization(id="org_f1_test", name="F1 Test Org", slug="f1-test-org")
        test_prop = Property(id="prop_f1_test", organization_id="org_f1_test", name="F1 Test Prop")
        active_agent = Agent(
            id="agt_f1_active",
            organization_id="org_f1_test",
            property_id="prop_f1_test",
            name="Seaside Concierge",
            agent_type="CONCIERGE",
            status=AgentStatus.ACTIVE
        )
        active_cfg = AgentConfig(
            id="cfg_agt_f1_active",
            agent_id="agt_f1_active",
            system_prompt="You are a helpful concierge assistant.",
            greeting="Welcome to Seaside Resort! How may I assist you?",
            model_name="sarvam-2b"
        )
        inactive_agent = Agent(
            id="agt_f1_inactive",
            organization_id="org_f1_test",
            property_id="prop_f1_test",
            name="Disabled Concierge",
            agent_type="CONCIERGE",
            status=AgentStatus.DISABLED
        )
        db.add_all([test_org, test_prop, active_agent, active_cfg, inactive_agent])
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test public agent endpoint for active agent
        resp = await client.get("/api/v1/public/agents/agt_f1_active")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == "agt_f1_active"
        assert data["display_name"] == "Seaside Concierge"
        assert "Welcome to Seaside Resort" in data["greeting"]
        assert "English" in data["languages"]
        assert data["branding"]["name"] == "Seaside Concierge"

        # 2. Test public agent endpoint for inactive agent and missing agent
        resp_inactive = await client.get("/api/v1/public/agents/agt_f1_inactive")
        assert resp_inactive.status_code == 404

        resp_missing = await client.get("/api/v1/public/agents/agt_non_existent")
        assert resp_missing.status_code == 404

        # 3. Test chat endpoint without organization_id/property_id
        # Turn 1
        chat_turn_1 = await client.post(
            "/api/v1/agents/agt_f1_active/chat",
            json={
                "message": "Hi, what are your check-in timings?",
                "channel": "web_widget"
            }
        )
        assert chat_turn_1.status_code == 200, chat_turn_1.text
        turn_1_data = chat_turn_1.json()
        conv_id = turn_1_data.get("conversation_id")
        guest_token = turn_1_data.get("guest_token")
        assert conv_id is not None
        assert guest_token is not None
        assert "response" in turn_1_data

        # 4. Turn 2: Provide conversation_id and guest_token
        chat_turn_2 = await client.post(
            "/api/v1/agents/agt_f1_active/chat",
            headers={"x-guest-token": guest_token},
            json={
                "message": "And is breakfast included?",
                "channel": "web_widget",
                "conversation_id": conv_id,
                "guest_token": guest_token
            }
        )
        assert chat_turn_2.status_code == 200, chat_turn_2.text
        turn_2_data = chat_turn_2.json()
        assert turn_2_data.get("conversation_id") == conv_id
        assert "response" in turn_2_data

        # 5. Non-ACTIVE agent chat rejection
        chat_inactive = await client.post(
            "/api/v1/agents/agt_f1_inactive/chat",
            json={
                "message": "Hello",
                "channel": "web_widget"
            }
        )
        assert chat_inactive.status_code == 400
