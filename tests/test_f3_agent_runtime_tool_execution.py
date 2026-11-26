import pytest
import uuid
from services.agent_runtime.tools import HospitalityToolRegistry, redact_sensitive_values
from services.database.models import Organization, Property, Room, LiveUpdate

@pytest.mark.asyncio
async def test_f3_agent_runtime_tool_security_and_error_handling(db_session, monkeypatch):
    """F3:
    - Tool execution checks that tool belongs to agent's configured enabled_tools.
    - An agent with empty enabled_tools cannot call any tool.
    - Parameter validation rejects invalid types.
    - Queries are scoped by organization_id and property_id.
    - Sensitive values (credit cards, passwords, tokens) are redacted from logs.
    - Database/SQL errors are never leaked to guests; polite fallback response is returned.
    """
    registry = HospitalityToolRegistry(db_session=db_session)

    org_a = str(uuid.uuid4())
    prop_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    prop_b = str(uuid.uuid4())

    # Create Room in Org A
    room_a = Room(
        id=str(uuid.uuid4()),
        organization_id=org_a,
        property_id=prop_a,
        room_number="101",
        room_type="Deluxe Suite",
        price_per_night=250.0,
        max_occupancy=2,
        is_available=True
    )
    # Create Room in Org B
    room_b = Room(
        id=str(uuid.uuid4()),
        organization_id=org_b,
        property_id=prop_b,
        room_number="999",
        room_type="Presidential Penthouse",
        price_per_night=1000.0,
        max_occupancy=4,
        is_available=True
    )
    # Create LiveUpdate in Org A
    notice_a = LiveUpdate(
        id=str(uuid.uuid4()),
        organization_id=org_a,
        property_id=prop_a,
        title="Pool Open Hotel A",
        content="Pool open until 10 PM",
        is_active=True
    )
    # Create LiveUpdate in Org B
    notice_b = LiveUpdate(
        id=str(uuid.uuid4()),
        organization_id=org_b,
        property_id=prop_b,
        title="VIP Notice Hotel B",
        content="Exclusive rooftop access for Org B guests",
        is_active=True
    )
    db_session.add(room_a)
    db_session.add(room_b)
    db_session.add(notice_a)
    db_session.add(notice_b)
    await db_session.commit()

    # 1. Unconfigured tool rejected
    res_unauth = await registry.execute_tool(
        tool_name="get_room_details",
        tool_args={"room_type": "Deluxe"},
        organization_id=org_a,
        property_id=prop_a,
        enabled_tools=["get_notices"]  # get_room_details is NOT enabled
    )
    assert res_unauth["success"] is False
    assert "not enabled" in res_unauth["error"]

    # 2. Agent with empty enabled_tools cannot call any tool
    res_empty_tools = await registry.execute_tool(
        tool_name="get_notices",
        tool_args={},
        organization_id=org_a,
        property_id=prop_a,
        enabled_tools=[]
    )
    assert res_empty_tools["success"] is False
    assert "not enabled" in res_empty_tools["error"]

    # 3. Invalid tool arguments type rejected
    res_invalid_args = await registry.execute_tool(
        tool_name="get_room_details",
        tool_args="invalid_string_args",  # Non-dict
        organization_id=org_a,
        property_id=prop_a,
        enabled_tools=["get_room_details"]
    )
    assert res_invalid_args["success"] is False
    assert "Invalid tool parameters" in res_invalid_args["error"]

    # 4. Cross-tenant scoping: Org A cannot query Org B's notices
    res_scoped = await registry.execute_tool(
        tool_name="get_notices",
        tool_args={},
        organization_id=org_a,
        property_id=prop_a,
        enabled_tools=["get_notices"]
    )
    assert res_scoped["success"] is True
    notices_a = res_scoped["result"]["notices"]
    assert len(notices_a) == 1
    assert notices_a[0]["title"] == "Pool Open Hotel A"
    # Ensure Org B's private VIP notice is NOT returned
    titles = [n["title"] for n in notices_a]
    assert "VIP Notice Hotel B" not in titles

    # 5. Sensitive data redaction
    log_data = {
        "guest_name": "Alice Smith",
        "card_number": "4111 2222 3333 4444",
        "user_password": "SuperSecretPassword123!",
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.signature",
        "nested": {
            "credit_card": "5500 0000 0000 0004",
            "api_key": "sk-live-1234567890abcdef"
        }
    }
    redacted = redact_sensitive_values(log_data)
    assert redacted["card_number"] == "[REDACTED]"
    assert redacted["user_password"] == "[REDACTED]"
    assert redacted["nested"]["credit_card"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    # Raw string text redaction
    text_with_cc = "Payment card: 4111-2222-3333-4444 for reservation"
    redacted_text = redact_sensitive_values(text_with_cc)
    assert "4111" not in redacted_text
    assert "[REDACTED_CARD]" in redacted_text

    # 6. Never leak SQL/database errors: simulated DB failure returns polite fallback message
    async def _failing_handler(*args, **kwargs):
        raise RuntimeError("OperationalError: table 'users' has no column 'ssn' (SELECT * FROM users)")

    monkeypatch.setattr(registry, "tool_get_notices", _failing_handler)

    res_sql_err = await registry.execute_tool(
        tool_name="get_notices",
        tool_args={},
        organization_id=org_a,
        property_id=prop_a,
        enabled_tools=["get_notices"]
    )
    assert res_sql_err["success"] is False
    assert "OperationalError" not in res_sql_err["error"]
    assert "SELECT" not in res_sql_err["error"]
    assert "I apologize, but I encountered an error retrieving that information" in res_sql_err["error"]
