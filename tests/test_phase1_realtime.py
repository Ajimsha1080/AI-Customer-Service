import pytest
import uuid
import json
import asyncio
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.auth import create_access_token
from services.realtime.broadcaster import (
    realtime_hub, generate_realtime_ticket, verify_realtime_ticket
)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def org_a_owner_headers():
    token = create_access_token(data={"sub": "usr_admin_01", "org_id": "org_azure_group", "role": "OWNER"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def org_b_owner_headers(client):
    res = client.post("/api/v1/auth/register", json={
        "email": f"org_b_{uuid.uuid4().hex[:6]}@example.com",
        "password": "Password123!",
        "full_name": "Org B Owner",
        "organization_name": "Org B Resort"
    })
    token = res.json()["access_token"]
    org_id = res.json()["user"]["organization_id"]
    return {"Authorization": f"Bearer {token}", "org_id": org_id}

@pytest.mark.asyncio
async def test_multi_tenant_channel_isolation():
    """1.1 Isolation: Events published to Org A must NEVER leak to Org B subscriber queues."""
    org_a = "org_alpha_test"
    org_b = "org_beta_test"

    # Subscriber A listens to Org A
    queue_a, _ = await realtime_hub.subscribe([f"org:{org_a}"])
    # Subscriber B listens to Org B
    queue_b, _ = await realtime_hub.subscribe([f"org:{org_b}"])

    try:
        # Publish event strictly to Org A
        event_a_id = await realtime_hub.publish(
            event_type="ROOM_STATUS_CHANGED",
            data={"room": "101", "status": "OCCUPIED"},
            organization_id=org_a
        )

        # Queue A must receive it within 1s
        event_received_a = await asyncio.wait_for(queue_a.get(), timeout=1.0)
        assert event_received_a["id"] == event_a_id
        assert event_received_a["organization_id"] == org_a
        assert event_received_a["data"]["room"] == "101"

        # Queue B must NOT have received any event (empty queue)
        assert queue_b.empty(), "Tenant isolation failure: Org B received Org A's confidential event!"

    finally:
        realtime_hub.unsubscribe(queue_a)
        realtime_hub.unsubscribe(queue_b)

@pytest.mark.asyncio
async def test_last_event_id_reconnection_replay():
    """1.2 Replay: Reconnecting client with Last-Event-ID must replay all missed events in sequence."""
    org_test = f"org_replay_{uuid.uuid4().hex[:6]}"
    channel = f"org:{org_test}"

    # Publish 3 events in sequence
    e1_id = await realtime_hub.publish("TEST_EVENT_1", {"seq": 1}, organization_id=org_test)
    e2_id = await realtime_hub.publish("TEST_EVENT_2", {"seq": 2}, organization_id=org_test)
    e3_id = await realtime_hub.publish("TEST_EVENT_3", {"seq": 3}, organization_id=org_test)

    # Reconnect with last_event_id = e1_id -> must receive e2 and e3
    q, missed = await realtime_hub.subscribe([channel], last_event_id=e1_id)
    try:
        assert len(missed) == 2
        assert missed[0]["id"] == e2_id
        assert missed[0]["data"]["seq"] == 2
        assert missed[1]["id"] == e3_id
        assert missed[1]["data"]["seq"] == 3
    finally:
        realtime_hub.unsubscribe(q)

def test_realtime_ticket_generation_and_verification(client, org_a_owner_headers):
    """1.3 Ticket Auth: 60s one-time ticket can be generated and verified for EventSource auth."""
    res = client.post("/api/v1/realtime/ticket", headers=org_a_owner_headers)
    assert res.status_code == 200
    ticket = res.json()["ticket"]
    assert ticket is not None

    # Verify ticket
    verified = verify_realtime_ticket(ticket)
    assert verified is not None
    assert verified["org_id"] == "org_azure_group"
    assert verified["role"] == "OWNER"

    # Fake/tampered ticket must fail verification
    assert verify_realtime_ticket("invalid.fake.ticket") is None

def test_conversation_and_message_turn_persistence(client, org_a_owner_headers):
    """1.4 Turn Persistence: /chat must persist turns as Conversation + Message rows."""
    # 1. Create a property and agent for Org A
    prop_res = client.post("/api/v1/properties", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "name": "Persistence Villa"
    })
    prop_id = prop_res.json()["id"]

    agent_res = client.post("/api/v1/agents", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "property_id": prop_id,
        "name": "Persistence Concierge",
        "agent_type": "CONCIERGE"
    })
    agent_id = agent_res.json()["id"]

    # 2. Chat with agent
    chat_res = client.post(
        f"/api/v1/agents/{agent_id}/chat",
        json={
            "organization_id": "org_azure_group",
            "property_id": prop_id,
            "message": "Do you have free Wi-Fi?",
            "channel": "web_widget"
        }
    )
    assert chat_res.status_code == 200
    conv_id = chat_res.json().get("conversation_id")
    assert conv_id is not None

    # 3. Retrieve conversation messages via /conversations/{id}/messages
    msgs_res = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=org_a_owner_headers)
    assert msgs_res.status_code == 200
    messages = msgs_res.json()
    assert len(messages) >= 2  # 1 guest message + 1 AI agent message
    assert messages[0]["sender_type"] == "guest"
    assert "Wi-Fi" in messages[0]["content"]
    assert messages[1]["sender_type"] == "agent"

def test_human_takeover_stops_ai_and_staff_reply_relays(client, org_a_owner_headers):
    """1.5 Human Takeover: AI stops responding when human takes over; staff can reply to guest."""
    prop_res = client.post("/api/v1/properties", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "name": "Takeover Villa"
    })
    prop_id = prop_res.json()["id"]

    agent_res = client.post("/api/v1/agents", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "property_id": prop_id,
        "name": "Takeover Concierge",
        "agent_type": "CONCIERGE"
    })
    agent_id = agent_res.json()["id"]

    # Start chat
    c_res = client.post(
        f"/api/v1/agents/{agent_id}/chat",
        json={
            "organization_id": "org_azure_group",
            "property_id": prop_id,
            "message": "I want to speak with staff immediately."
        }
    )
    conv_id = c_res.json()["conversation_id"]

    # Staff takes over conversation
    takeover_res = client.post(
        f"/api/v1/conversations/{conv_id}/takeover",
        headers=org_a_owner_headers,
        json={"reason": "Guest escalation"}
    )
    assert takeover_res.status_code == 200
    assert takeover_res.json()["status"] == "HUMAN_STAFF_TAKEN_OVER"

    # Guest sends follow up message -> AI must NOT answer, returns human takeover notice
    followup_res = client.post(
        f"/api/v1/agents/{agent_id}/chat",
        json={
            "organization_id": "org_azure_group",
            "property_id": prop_id,
            "conversation_id": conv_id,
            "message": "Are you still an AI?"
        }
    )
    assert followup_res.status_code == 200
    assert followup_res.json()["status"] == "HUMAN_STAFF_TAKEN_OVER"
    assert "staff member has taken over" in followup_res.json()["response"].lower()

    # Staff sends reply message
    staff_msg_res = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=org_a_owner_headers,
        json={"content": "Hello, this is the front desk manager. How can I help?"}
    )
    assert staff_msg_res.status_code == 200
    assert staff_msg_res.json()["sender_type"] == "STAFF"

def test_integration_sync_endpoint(client, org_a_owner_headers):
    """1.6 Integration Sync: /sync updates last_synced_at and status."""
    connect_res = client.post(
        "/api/v1/live-updates/integrations",
        headers=org_a_owner_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_test",
            "name": "Sync Test ERP",
            "source_type": "REST_API",
            "source_url": "https://example.com/api/rooms",
            "credentials": "token_123"
        }
    )
    src_id = connect_res.json()["id"]

    sync_res = client.post(
        f"/api/v1/live-updates/integrations/{src_id}/sync?organization_id=org_azure_group",
        headers=org_a_owner_headers
    )
    assert sync_res.status_code == 200
    data = sync_res.json()
    assert data["status"] == "SYNCED"
    assert data["last_synced_at"] is not None

def test_streaming_chat_endpoint(client, org_a_owner_headers):
    """1.7 Streaming Chat: /chat/stream returns text/event-stream chunks."""
    prop_res = client.post("/api/v1/properties", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "name": "Stream Villa"
    })
    prop_id = prop_res.json()["id"]

    agent_res = client.post("/api/v1/agents", headers=org_a_owner_headers, json={
        "organization_id": "org_azure_group",
        "property_id": prop_id,
        "name": "Stream Concierge",
        "agent_type": "CONCIERGE"
    })
    agent_id = agent_res.json()["id"]

    res_stream = client.post(
        f"/api/v1/agents/{agent_id}/chat/stream",
        json={
            "organization_id": "org_azure_group",
            "property_id": prop_id,
            "message": "Tell me about checkout timings."
        }
    )
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers.get("content-type", "")
    content = res_stream.text
    assert "data: " in content
    assert "done" in content
