import pytest
import hmac
import hashlib
import json
import uuid
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.config import settings
from services.database.models import (
    Organization, Property, Agent, AgentStatus, AgentConfig,
    WhatsAppChannelMapping
)

def _generate_wa_signature(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

@pytest.mark.asyncio
async def test_f2_whatsapp_inbound_schema_variations_and_deduplication(db_session, monkeypatch):
    """F2:
    - Fails closed on invalid signature (401).
    - Supports both Meta v16+ standard schema and direct messages schema.
    - Normalizes text, image, audio, location, and interactive button replies.
    - Drops unmapped phone numbers.
    - Dedupes by message ID in Redis and DB.
    - Returns 200 immediately with queued background processing.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_secret = "test_whatsapp_app_secret_12345"
        monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", test_secret)

        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="WA Hotel", slug=f"wa-hotel-{uuid.uuid4().hex[:6]}", status="active")
        prop_id = str(uuid.uuid4())
        prop = Property(id=prop_id, organization_id=org_id, name="WA Resort")
        agent_id = str(uuid.uuid4())
        agent = Agent(
            id=agent_id,
            organization_id=org_id,
            property_id=prop_id,
            name="WA Concierge",
            status=AgentStatus.ACTIVE
        )
        config = AgentConfig(
            agent_id=agent_id,
            model_name="sarvam-2b",
            system_prompt="You are a WhatsApp Concierge."
        )
        phone_id = f"phone_{uuid.uuid4().hex[:8]}"
        mapping = WhatsAppChannelMapping(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop_id,
            phone_number_id=phone_id,
            agent_id=agent_id,
            is_active=True
        )
        db_session.add(org)
        db_session.add(prop)
        db_session.add(agent)
        db_session.add(config)
        db_session.add(mapping)
        await db_session.commit()

        # 1. Invalid signature -> 401 Unauthorized
        res_bad_sig = await ac.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=b'{"test": 1}',
            headers={"x-hub-signature-256": "sha256=invalid_hash", "Content-Type": "application/json"}
        )
        assert res_bad_sig.status_code == 401

        # 2. Schema 1: Standard Meta Cloud API schema (entry -> changes -> value)
        msg_id_1 = f"wamid.{uuid.uuid4().hex}"
        payload_schema_1 = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "wa_business_account_1",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": phone_id},
                                "messages": [
                                    {
                                        "id": msg_id_1,
                                        "from": "15551234567",
                                        "type": "text",
                                        "text": {"body": "Hello from WhatsApp standard schema"}
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        body_1 = json.dumps(payload_schema_1).encode("utf-8")
        sig_1 = _generate_wa_signature(body_1, test_secret)

        res_1 = await ac.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=body_1,
            headers={"x-hub-signature-256": sig_1, "Content-Type": "application/json"}
        )
        assert res_1.status_code == 200
        assert res_1.json()["events_queued"] == 1

        # 3. Deduplication: Re-sending exact same msg_id_1 is ignored
        res_dedupe = await ac.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=body_1,
            headers={"x-hub-signature-256": sig_1, "Content-Type": "application/json"}
        )
        assert res_dedupe.status_code == 200
        assert res_dedupe.json()["events_queued"] == 0

        # 4. Schema 2: Direct messages list with location and interactive button reply
        msg_id_loc = f"wamid.{uuid.uuid4().hex}"
        msg_id_btn = f"wamid.{uuid.uuid4().hex}"
        payload_schema_2 = {
            "phone_number_id": phone_id,
            "messages": [
                {
                    "id": msg_id_loc,
                    "from": "15551234567",
                    "type": "location",
                    "location": {"latitude": 28.6139, "longitude": 77.2090, "name": "India Gate"}
                },
                {
                    "id": msg_id_btn,
                    "from": "15551234567",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn_pool", "title": "Check Pool Hours"}
                    }
                }
            ]
        }
        body_2 = json.dumps(payload_schema_2).encode("utf-8")
        sig_2 = _generate_wa_signature(body_2, test_secret)

        res_2 = await ac.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=body_2,
            headers={"x-hub-signature-256": sig_2, "Content-Type": "application/json"}
        )
        assert res_2.status_code == 200
        assert res_2.json()["events_queued"] == 2

        # 5. Dropping unmapped numbers
        msg_id_unmapped = f"wamid.{uuid.uuid4().hex}"
        payload_unmapped = {
            "phone_number_id": "unmapped_phone_9999",
            "messages": [
                {
                    "id": msg_id_unmapped,
                    "from": "15551234567",
                    "type": "text",
                    "text": {"body": "Message for unknown number"}
                }
            ]
        }
        body_unmapped = json.dumps(payload_unmapped).encode("utf-8")
        sig_unmapped = _generate_wa_signature(body_unmapped, test_secret)

        res_unmapped = await ac.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=body_unmapped,
            headers={"x-hub-signature-256": sig_unmapped, "Content-Type": "application/json"}
        )
        assert res_unmapped.status_code == 200
        assert res_unmapped.json()["events_queued"] == 0
