import io
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token
from services.billing.metering import SaaSMeteringService
from services.database.session import AsyncSessionLocal
from services.database.models import User, Organization, Property, Agent, Conversation, Message, SupportTicket, Document, Subscription, ConversationStatus

@pytest.fixture
def superadmin_headers():
    token = create_access_token({
        "sub": "usr_superadmin",
        "email": "superadmin@azurehostel.com",
        "role": "SUPER_ADMIN",
        "organization_id": "org_azure_group"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_full_lifecycle_e2e(superadmin_headers):
    """
    Phase 4 E2E Test:
    User signup -> Org provisioning -> Agent creation -> Document RAG ingestion ->
    Guest chat turn with conversation_id -> Handoff to human -> Staff inbox relay.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. User Registration & Org Provisioning
        unique_suffix = uuid.uuid4().hex[:6]
        signup_res = await ac.post("/api/v1/auth/register", json={
            "email": f"owner_{unique_suffix}@p4resort.com",
            "password": "SecurePassword123!",
            "full_name": f"Owner {unique_suffix}",
            "organization_name": f"P4 Resort {unique_suffix}"
        })
        assert signup_res.status_code == 200
        data = signup_res.json()
        token = data["access_token"]
        org_id = data["user"]["organization_id"]
        owner_id = data["user"]["id"]
        owner_headers = {"Authorization": f"Bearer {token}"}

        # 2. Create Property
        prop_res = await ac.post("/api/v1/properties", json={
            "organization_id": org_id,
            "name": f"P4 Ocean Villa {unique_suffix}"
        }, headers=owner_headers)
        assert prop_res.status_code == 200
        prop_id = prop_res.json()["id"]

        # 3. Create Agent
        agent_res = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "type": "concierge",
            "name": "P4 Concierge",
            "system_prompt": "You are the AI Concierge for P4 Ocean Villa. Mention our Infinity Pool and Breakfast timings."
        }, headers=owner_headers)
        assert agent_res.status_code == 200
        agent_id = agent_res.json()["id"]

        # 4. Ingest Document into Knowledge Base
        doc_content = "The Infinity Pool at P4 Ocean Villa is open daily from 7:00 AM to 9:00 PM. Complimentary breakfast is served from 8:00 AM to 10:30 AM."
        file_bytes = io.BytesIO(doc_content.encode("utf-8"))
        upload_res = await ac.post(
            "/api/v1/knowledge/documents/upload",
            data={
                "organization_id": org_id,
                "property_id": prop_id,
                "title": "P4 Resort Amenities Guide"
            },
            files={"file": ("amenities.txt", file_bytes, "text/plain")},
            headers=owner_headers
        )
        assert upload_res.status_code == 200
        assert upload_res.json()["status"] == "INDEXED"

        # 5. Guest Chat Turn (First turn)
        chat_1_res = await ac.post(f"/api/v1/agents/{agent_id}/chat", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "message": "Hello! What are the pool hours?",
            "channel": "web_widget"
        })
        assert chat_1_res.status_code == 200
        chat_1_data = chat_1_res.json()
        assert "response" in chat_1_data
        conv_id = chat_1_data["conversation_id"]
        assert conv_id is not None

        # 6. Guest Chat Follow-up Turn preserving conversation_id
        chat_2_res = await ac.post(f"/api/v1/agents/{agent_id}/chat", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "conversation_id": conv_id,
            "message": "Thank you! I would like to speak to a human staff member.",
            "channel": "web_widget"
        })
        assert chat_2_res.status_code == 200
        chat_2_data = chat_2_res.json()
        assert chat_2_data["conversation_id"] == conv_id

        # 7. Verify Conversation is marked for Human Takeover in DB
        async with AsyncSessionLocal() as session:
            conv = await session.get(Conversation, conv_id)
            assert conv is not None
            assert conv.status == ConversationStatus.HUMAN_STAFF_TAKEN_OVER or conv.is_human_takeover is True

            # Verify Messages Turn History
            messages_res = await ac.get(f"/api/v1/conversations/{conv_id}/messages", headers=owner_headers)
            assert messages_res.status_code == 200
            msgs = messages_res.json()
            assert len(msgs) >= 2
            assert any(m["sender_type"] == "guest" for m in msgs)
            assert any(m["sender_type"] == "agent" for m in msgs)

        # 8. Staff Member replies from Inbox
        staff_reply_res = await ac.post(f"/api/v1/conversations/{conv_id}/messages", json={
            "content": "Hello! This is Maria from Front Desk. How may I assist you with your stay?"
        }, headers=owner_headers)
        assert staff_reply_res.status_code == 200
        reply_data = staff_reply_res.json()
        assert reply_data["sender_type"] == "STAFF"
        assert "Maria" in reply_data["content"]

        # 9. Verify subsequent guest message gets staff takeover hold message rather than AI generating
        chat_3_res = await ac.post(f"/api/v1/agents/{agent_id}/chat", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "conversation_id": conv_id,
            "message": "Can I get extra towels sent to room 204?",
            "channel": "web_widget"
        })
        assert chat_3_res.status_code == 200
        chat_3_data = chat_3_res.json()
        assert chat_3_data["is_human_takeover"] is True
        assert "front desk" in chat_3_data["response"].lower()

@pytest.mark.asyncio
async def test_billing_tier_enforcement_and_seat_limits(superadmin_headers):
    """
    Verifies Starter plan boundaries:
    - Agent count quota (Starter allows max 2 agents).
    - Team member seats quota (Starter allows max 2 seats).
    - Upgrading tier increases limits dynamically.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        unique_suffix = uuid.uuid4().hex[:6]
        signup_res = await ac.post("/api/v1/auth/register", json={
            "email": f"starter_{unique_suffix}@resort.com",
            "password": "Password123!",
            "full_name": f"Starter Admin {unique_suffix}",
            "organization_name": f"Starter Resort {unique_suffix}"
        })
        assert signup_res.status_code == 200
        data = signup_res.json()
        owner_headers = {"Authorization": f"Bearer {data['access_token']}"}
        org_id = data["user"]["organization_id"]

        prop_res = await ac.post("/api/v1/properties", json={
            "organization_id": org_id,
            "name": f"Starter Prop {unique_suffix}"
        }, headers=owner_headers)
        prop_id = prop_res.json()["id"]

        # 1. Create 1st Agent (Allowed on Starter)
        a1_res = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "type": "concierge",
            "name": "Agent One"
        }, headers=owner_headers)
        assert a1_res.status_code == 200

        # 2. Create 2nd Agent (Allowed on Starter, max is 2)
        a2_res = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "type": "booking",
            "name": "Agent Two"
        }, headers=owner_headers)
        assert a2_res.status_code == 200

        # 3. Create 3rd Agent -> Must be rejected with 402 Payment Required!
        a3_res = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "type": "support",
            "name": "Agent Three"
        }, headers=owner_headers)
        assert a3_res.status_code == 402
        assert "Plan limit reached" in a3_res.json()["detail"] or "Agent creation limit reached" in a3_res.json()["detail"]

        # 4. Check Team Member Seats Quota
        # Currently 1 user exists (the owner). Starter max_seats is 2.
        # First invitation: allowed
        inv1_res = await ac.post(f"/api/v1/organizations/{org_id}/invitations", json={
            "email": f"staff1_{unique_suffix}@resort.com",
            "role": "STAFF"
        }, headers=owner_headers)
        assert inv1_res.status_code == 200

        # Accept the invitation or create a second user to consume the seat
        async with AsyncSessionLocal() as session:
            user2 = User(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                email=f"staff2_{unique_suffix}@resort.com",
                hashed_password="mock_hashed_password",
                full_name="Staff 2",
                role="STAFF",
                is_active=True
            )
            session.add(user2)
            await session.commit()

        # Now 2 users exist in org_id -> Reached Starter limit (max_seats: 2)
        # Attempting to invite another member must fail with 402!
        inv2_res = await ac.post(f"/api/v1/organizations/{org_id}/invitations", json={
            "email": f"staff3_{unique_suffix}@resort.com",
            "role": "STAFF"
        }, headers=owner_headers)
        assert inv2_res.status_code == 402
        assert "seat limit reached" in inv2_res.json()["detail"].lower()

        # 5. Super Admin upgrades organization to BUSINESS
        upgrade_res = await ac.post(f"/api/v1/billing/subscription/upgrade?organization_id={org_id}", json={
            "plan_name": "BUSINESS"
        }, headers=superadmin_headers)
        assert upgrade_res.status_code == 200
        assert upgrade_res.json()["plan_name"] == "BUSINESS"

        # 6. Under BUSINESS plan: creating 3rd agent now SUCCEEDS!
        a3_retry_res = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "type": "support",
            "name": "Agent Three"
        }, headers=owner_headers)
        assert a3_retry_res.status_code == 200

        # 7. Under BUSINESS plan: inviting additional team member now SUCCEEDS!
        inv3_res = await ac.post(f"/api/v1/organizations/{org_id}/invitations", json={
            "email": f"staff3_{unique_suffix}@resort.com",
            "role": "STAFF"
        }, headers=owner_headers)
        assert inv3_res.status_code == 200

@pytest.mark.asyncio
async def test_conversation_tenant_isolation(superadmin_headers):
    """
    Verifies that conversations and staff takeover cannot be accessed across tenant boundaries.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        u1 = uuid.uuid4().hex[:6]
        u2 = uuid.uuid4().hex[:6]

        res1 = await ac.post("/api/v1/auth/register", json={
            "email": f"org1_{u1}@resort.com",
            "password": "Password123!",
            "full_name": f"Org 1 User",
            "organization_name": f"Org 1 {u1}"
        })
        token1 = res1.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}
        org1_id = res1.json()["user"]["organization_id"]

        res2 = await ac.post("/api/v1/auth/register", json={
            "email": f"org2_{u2}@resort.com",
            "password": "Password123!",
            "full_name": f"Org 2 User",
            "organization_name": f"Org 2 {u2}"
        })
        token2 = res2.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        prop1_res = await ac.post("/api/v1/properties", json={
            "organization_id": org1_id,
            "name": f"Prop 1 {u1}"
        }, headers=headers1)
        prop1_id = prop1_res.json()["id"]

        agent1_res = await ac.post("/api/v1/agents", json={
            "organization_id": org1_id,
            "property_id": prop1_id,
            "type": "concierge",
            "name": "Org 1 Agent"
        }, headers=headers1)
        agent1_id = agent1_res.json()["id"]

        chat_res = await ac.post(f"/api/v1/agents/{agent1_id}/chat", json={
            "organization_id": org1_id,
            "property_id": prop1_id,
            "message": "Hello from guest in Org 1",
            "channel": "web_widget"
        })
        conv_id = chat_res.json()["conversation_id"]

        # Org 2 user attempts to view Org 1 conversation messages -> Must return 404
        steal_msg_res = await ac.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers2)
        assert steal_msg_res.status_code == 404

        # Org 2 user attempts to take over Org 1 conversation -> Must return 404
        steal_takeover_res = await ac.post(f"/api/v1/conversations/{conv_id}/takeover", json={
            "reason": "Malicious Takeover Attempt"
        }, headers=headers2)
        assert steal_takeover_res.status_code == 404

        # Org 2 user attempts to send message to Org 1 conversation -> Must return 404
        steal_reply_res = await ac.post(f"/api/v1/conversations/{conv_id}/messages", json={
            "content": "Malicious message injection"
        }, headers=headers2)
        assert steal_reply_res.status_code == 404
