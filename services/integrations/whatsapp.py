import hmac
import hashlib
import logging
from typing import Dict, Any, Optional
import httpx

from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.whatsapp")

class WhatsAppCloudAPIClient:
    """Meta WhatsApp Business Cloud API Client & Webhook Verifier."""

    def __init__(self):
        self.api_key = settings.WHATSAPP_API_KEY
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "mock_phone_number_id")
        self.app_secret = os.getenv("WHATSAPP_APP_SECRET", "mock_app_secret")
        self.verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "hospitality_whatsapp_verify_token")

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verifies X-Hub-Signature-256 header sent by Meta webhooks."""
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected_hash = hmac.new(
            self.app_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        incoming_hash = signature_header.replace("sha256=", "").strip()
        return hmac.compare_digest(expected_hash, incoming_hash)

    async def send_text_message(self, recipient_phone: str, text: str) -> Dict[str, Any]:
        """Sends an outbound WhatsApp text message via Meta Graph API."""
        if not self.api_key or self.api_key.startswith("mock"):
            logger.info(f"[WhatsApp SIMULATED] To: {recipient_phone} Text: '{text[:50]}...'")
            return {"status": "sent", "mode": "SIMULATED_WHATSAPP", "recipient": recipient_phone}

        url = f"https://graph.facebook.com/v19.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text}
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    return {"status": "sent", "mode": "META_WHATSAPP_CLOUD_API", "data": res.json()}
                logger.error(f"WhatsApp API Error ({res.status_code}): {res.text}")
                return {"status": "error", "code": res.status_code, "detail": res.text}
        except Exception as e:
            logger.error(f"WhatsApp API Exception: {e}")
            return {"status": "exception", "detail": str(e)}

import os
