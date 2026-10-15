import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import app
from services.database.session import AsyncSessionLocal
from services.database.models import (
    User, Organization, Property, Agent, Conversation, Message, UsageEvent, ConversationStatus
)

client = TestClient(app)

@pytest.mark.asyncio
async def test_analytics_computation_and_no_500_with_seeded_conversations():
    """Phase 0.4: /api/v1/analytics returns 200 with accurate metrics (resolution rate,
    escalation, latency, channel split, cost) and never 500s when conversations exist.
    """
    domain = f"corp_{uuid.uuid4().hex[:8]}.test"
    owner_email = f"analytics_owner@{domain}"

    reg = client.post("/api/v1/auth/register", json={
        "email": owner_email,
        "password": "StrongPassword_2026!",
        "full_name": "Analytics Owner",
        "organization_name": "Analytics Grand Resort"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncSessionLocal() as db:
        # Seed a property
        prop = Property(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Grand Palm Wing"
        )
        db.add(prop)
        await db.flush()

        # Seed an agent
        agent = Agent(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            name="Analytics Concierge",
            agent_type="CONCIERGE"
        )
        db.add(agent)
        await db.flush()

        # Seed 4 conversations:
        # Conv 1: Resolved (web_widget)
        c1 = Conversation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            channel="web_widget",
            channel_user_id="user_01",
            customer_name="Guest 1",
            status=ConversationStatus.RESOLVED,
            is_human_takeover=False
        )
        # Conv 2: Human takeover (whatsapp)
        c2 = Conversation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            channel="whatsapp",
            channel_user_id="+1234567890",
            customer_name="Guest 2",
            status=ConversationStatus.HUMAN_STAFF_TAKEN_OVER,
            is_human_takeover=True
        )
        # Conv 3: Human requested (voice)
        c3 = Conversation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            channel="voice",
            channel_user_id="+1987654321",
            customer_name="Guest 3",
            status=ConversationStatus.HUMAN_REQUESTED,
            is_human_takeover=False
        )
        # Conv 4: AI Active (web_widget)
        c4 = Conversation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            channel="web_widget",
            channel_user_id="user_04",
            customer_name="Guest 4",
            status=ConversationStatus.AI_ACTIVE,
            is_human_takeover=False
        )
        db.add_all([c1, c2, c3, c4])
        await db.flush()

        # Seed Messages with latency_ms in metadata_json
        m1 = Message(
            id=str(uuid.uuid4()),
            conversation_id=c1.id,
            sender_type="AI",
            content="Welcome to our hotel!",
            metadata_json={"latency_ms": 120}
        )
        m2 = Message(
            id=str(uuid.uuid4()),
            conversation_id=c2.id,
            sender_type="AI",
            content="I am transferring you to front desk.",
            metadata_json={"latency_ms": 280}
        )
        db.add_all([m1, m2])

        # Seed UsageEvents with estimated_cost
        u1 = UsageEvent(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            conversation_id=c1.id,
            event_type="llm_token",
            quantity=1000,
            estimated_cost=0.0025
        )
        u2 = UsageEvent(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            agent_id=agent.id,
            conversation_id=c3.id,
            event_type="voice_minute",
            quantity=5,
            estimated_cost=0.0450
        )
        db.add_all([u1, u2])
        await db.commit()

    # Call /api/v1/analytics
    res = client.get("/api/v1/analytics", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["organization_id"] == org_id
    assert data["total_conversations"] == 4
    assert data["total_usage_events"] == 2

    # Expected:
    # 2 escalated (c2 takeover, c3 HUMAN_REQUESTED) -> 2/4 = 50.0%
    # 1 resolved (c1 RESOLVED) -> 1/4 = 25.0%
    assert data["ai_resolution_rate"] == "25.0%"
    assert data["human_escalation_rate"] == "50.0%"

    # Latencies: (120 + 280) / 2 = 200 ms
    assert data["average_response_time_ms"] == 200

    # Total cost: 0.0025 + 0.0450 = 0.0475
    assert data["total_cost_usd"] == 0.0475

    # Channels: 2 web_widget (50.0%), 1 whatsapp (25.0%), 1 voice (25.0%)
    channels = data["top_channels"]
    assert channels["web_widget"] == "50.0%"
    assert channels["whatsapp"] == "25.0%"
    assert channels["voice"] == "25.0%"
