import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from apps.api.main import app
from services.database.session import AsyncSessionLocal
from services.database.models import Agent, AgentStatus, AgentType, Resident, Organization, Property, LiveUpdate, Conversation
from services.agent_runtime.tools import HospitalityToolRegistry

@pytest.mark.asyncio
async def test_c8_reject_non_active_agents(prepare_db):
    """C8: Reject chat for non-ACTIVE agents."""
    transport = ASGITransport(app=app)
    inactive_agent_id = f"agt_inactive_{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as db:
        agt = Agent(
            id=inactive_agent_id,
            organization_id="org_azure_group",
            property_id="prop_azure_palm_resort",
            name="Disabled Concierge",
            agent_type=AgentType.CONCIERGE,
            status=AgentStatus.DISABLED
        )
        db.add(agt)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/v1/agents/{inactive_agent_id}/chat",
            json={"message": "Hello"}
        )
        assert res.status_code == 400
        assert "not active" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_c8_server_side_scoping_and_conversation_isolation(prepare_db):
    """C8: Client cannot spoof property_id/org, and conversation hijacking starts fresh conversation."""
    transport = ASGITransport(app=app)

    # 1. Create a conversation under org_azure_group
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Chat without org/property sent by client -> succeeds, server derives from agent
        res1 = await client.post(
            "/api/v1/agents/agt_hostel_01/chat",
            json={"message": "What is the breakfast schedule?", "property_id": "spoofed_property_id"}
        )
        assert res1.status_code == 200
        data1 = res1.json()
        conv_id_1 = data1["conversation_id"]
        guest_token = data1.get("guest_token")
        assert guest_token is not None

        # Verify in DB that conversation actually used agent's property_id, not spoofed_property_id
        async with AsyncSessionLocal() as db:
            stmt = select(Conversation).where(Conversation.id == conv_id_1)
            c_res = await db.execute(stmt)
            c_obj = c_res.scalar_one()
            assert c_obj.property_id == "prop_azure_palm_resort"
            assert c_obj.organization_id == "org_azure_group"

        # 2. Attempt to hijack conversation from another agent / tenant
        # Create second agent in different tenant
        tenant_b_org_id = f"org_other_{uuid.uuid4().hex[:6]}"
        agent_b_id = f"agt_b_{uuid.uuid4().hex[:6]}"
        async with AsyncSessionLocal() as db:
            db.add(Organization(id=tenant_b_org_id, name="Other Hostel", slug=f"other-{uuid.uuid4().hex[:4]}", status="active"))
            db.add(Property(id=f"prop_b_{uuid.uuid4().hex[:6]}", organization_id=tenant_b_org_id, name="Other Prop"))
            db.add(Agent(id=agent_b_id, organization_id=tenant_b_org_id, property_id=f"prop_b_{uuid.uuid4().hex[:6]}", name="Agent B", status=AgentStatus.ACTIVE))
            await db.commit()

        # Send request to Agent B passing Tenant A's conversation_id
        res2 = await client.post(
            f"/api/v1/agents/{agent_b_id}/chat",
            json={"message": "Hello from hijacker", "conversation_id": conv_id_1}
        )
        assert res2.status_code == 200
        data2 = res2.json()
        # Must NOT attach to conv_id_1; MUST start a new conversation
        assert data2["conversation_id"] != conv_id_1

@pytest.mark.asyncio
async def test_c8_resident_pii_redaction_and_tool_scoping(prepare_db):
    """C8: Redact PII in tool_get_resident_info and verify multi-tenant isolation in tools."""
    tools = HospitalityToolRegistry()

    # Seed resident and live update in org_azure_group
    resident_id = f"res_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        res_obj = Resident(
            id=resident_id,
            organization_id="org_azure_group",
            property_id="prop_azure_palm_resort",
            name="John Doe",
            room_number="101A",
            block="East",
            fee_status="PAID_IN_FULL",
            check_in_date="2026-01-01",
            phone="+1234567890",
            emergency_contact="+1987654321"
        )
        db.add(res_obj)

        # Seed update in another org
        db.add(LiveUpdate(
            id=f"upd_other_{uuid.uuid4().hex[:6]}",
            organization_id="org_other_tenant",
            property_id="prop_azure_palm_resort",  # Same property string, different org
            title="Secret Tenant B Announcement",
            content="Sensitive internal info",
            is_active=True
        ))
        await db.commit()

    # 1. PII Redaction Check: Phone, emergency contact, and fee status MUST NOT be returned
    info = await tools.tool_get_resident_info(
        {"resident_id": resident_id},
        organization_id="org_azure_group",
        property_id="prop_azure_palm_resort"
    )
    assert info.get("name") == "John Doe"
    assert info.get("room_number") == "101A"
    assert "phone" not in info
    assert "emergency_contact" not in info
    assert "fee_status" not in info

    # 2. Cross-tenant tool scoping: A different tenant querying for this resident gets NOT FOUND
    info_other = await tools.tool_get_resident_info(
        {"resident_id": resident_id},
        organization_id="org_other_tenant",
        property_id="prop_azure_palm_resort"
    )
    assert info_other.get("status") == "RESIDENT_NOT_FOUND"

    # 3. Live notices scoping: querying org_azure_group must NOT return Tenant B's updates
    notices = await tools.tool_get_notices(
        {},
        organization_id="org_azure_group",
        property_id="prop_azure_palm_resort"
    )
    notice_titles = [n["title"] for n in notices.get("notices", [])]
    assert "Secret Tenant B Announcement" not in notice_titles
