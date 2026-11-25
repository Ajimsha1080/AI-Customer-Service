import hmac
import hashlib
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from apps.api.main import app
from apps.api.config import settings
from services.integrations.whatsapp_bsp import WhatsAppBusinessService
from services.database.session import AsyncSessionLocal
from services.database.models import WhatsAppChannelMapping, Agent, AgentStatus, ProcessedWebhookEvent

@pytest.mark.asyncio
async def test_c7_whatsapp_secrets_and_defaults():
    """Verify default forgeable secrets are eliminated and require explicit config."""
    # Custom instance with no secrets configured
    empty_bsp = WhatsAppBusinessService(verify_token="", app_secret="")
    assert empty_bsp.verify_webhook_challenge("subscribe", "wa_verify_token_default", "12345") is None
    assert empty_bsp.verify_inbound_signature(b"{}", "sha256=abcdef") is False

    # Configured instance
    bsp = WhatsAppBusinessService(verify_token="test_valid_verify_token", app_secret="test_valid_app_secret")
    assert bsp.verify_webhook_challenge("subscribe", "test_valid_verify_token", "challenge_123") == "challenge_123"
    assert bsp.verify_webhook_challenge("subscribe", "wa_verify_token_default", "challenge_123") is None

    # Signature verification
    body = b'{"test": "payload"}'
    valid_sig = "sha256=" + hmac.new(b"test_valid_app_secret", body, hashlib.sha256).hexdigest()
    assert bsp.verify_inbound_signature(body, valid_sig) is True
    assert bsp.verify_inbound_signature(body, "sha256=invalid") is False

@pytest.mark.asyncio
async def test_c7_whatsapp_webhook_verification_endpoints():
    """Test Meta webhook verification GET endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid verify token -> 403
        res_invalid = await client.get("/api/v1/integrations/whatsapp/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "112233"
        })
        assert res_invalid.status_code == 403

        # Valid verify token -> 200 with challenge
        res_valid = await client.get("/api/v1/integrations/whatsapp/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "112233"
        })
        assert res_valid.status_code == 200
        assert "112233" in res_valid.text

@pytest.mark.asyncio
async def test_c7_whatsapp_channel_routing_and_deduplication(prepare_db):
    """Test channel mapping, dropping unmapped messages, and message deduplication."""
    transport = ASGITransport(app=app)
    mapped_phone_id = f"phone_{uuid.uuid4().hex[:8]}"
    unmapped_phone_id = f"phone_{uuid.uuid4().hex[:8]}"

    # Set up mapping for org_azure_group and agt_hostel_01
    async with AsyncSessionLocal() as db:
        mapping = WhatsAppChannelMapping(
            id=f"map_{uuid.uuid4().hex[:8]}",
            phone_number_id=mapped_phone_id,
            organization_id="org_azure_group",
            property_id="prop_azure_palm_resort",
            agent_id="agt_hostel_01",
            is_active=True
        )
        db.add(mapping)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unmapped phone_number_id -> DROPPED (0 events processed)
        unmapped_payload = json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": unmapped_phone_id},
                        "messages": [{
                            "from": "15551234567",
                            "id": f"wamid_{uuid.uuid4().hex}",
                            "text": {"body": "Hello unmapped"}
                        }]
                    }
                }]
            }]
        }).encode("utf-8")

        sig_unmapped = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode("utf-8"), unmapped_payload, hashlib.sha256).hexdigest()
        res_unmapped = await client.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=unmapped_payload,
            headers={"x-hub-signature-256": sig_unmapped, "Content-Type": "application/json"}
        )
        assert res_unmapped.status_code == 200
        assert res_unmapped.json()["events_processed"] == 0

        # 2. Mapped phone_number_id -> PROCESSED (1 event processed)
        msg_id = f"wamid_{uuid.uuid4().hex}"
        mapped_payload = json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_2",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": mapped_phone_id},
                        "messages": [{
                            "from": "15559876543",
                            "id": msg_id,
                            "text": {"body": "What are your breakfast hours?"}
                        }]
                    }
                }]
            }]
        }).encode("utf-8")

        sig_mapped = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode("utf-8"), mapped_payload, hashlib.sha256).hexdigest()
        res_mapped = await client.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=mapped_payload,
            headers={"x-hub-signature-256": sig_mapped, "Content-Type": "application/json"}
        )
        assert res_mapped.status_code == 200
        assert res_mapped.json()["events_processed"] == 1

        # 3. Duplicate message ID replay -> DEDUPLICATED (0 events processed)
        res_dup = await client.post(
            "/api/v1/integrations/whatsapp/webhook",
            content=mapped_payload,
            headers={"x-hub-signature-256": sig_mapped, "Content-Type": "application/json"}
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["events_processed"] == 0
