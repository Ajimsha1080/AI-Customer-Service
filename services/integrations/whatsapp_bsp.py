import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger("hospitality_agent_cloud.integrations.whatsapp_bsp")

class WhatsApp24HourWindowViolation(Exception):
    pass

class WhatsAppBusinessService:
    """
    Official WhatsApp Business Cloud API Integration:
    - Webhook challenge verification.
    - Meta X-Hub-Signature-256 validation.
    - 24-hour Customer Care Window enforcement (requires registered template if closed).
    """
    def __init__(self, verify_token: str = "wa_verify_token_default", app_secret: str = "wa_app_secret_default"):
        self.verify_token = verify_token
        self.app_secret = app_secret

    def verify_webhook_challenge(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Handles Meta webhook verification GET request."""
        if mode == "subscribe" and token == self.verify_token:
            logger.info("[WhatsApp] Webhook challenge verified successfully.")
            return challenge
        logger.warning(f"[WhatsApp] Webhook challenge failed (mode={mode}).")
        return None

    def verify_inbound_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verifies Meta X-Hub-Signature-256 header: 'sha256=<hex>'."""
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        provided_sig = signature_header.split("=")[1]
        expected_sig = hmac.new(self.app_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided_sig, expected_sig)

    def can_send_freeform_message(self, last_inbound_msg_time: Optional[datetime]) -> bool:
        """
        Meta WhatsApp 24-Hour Policy:
        Businesses can send freeform messages within 24 hours of the guest's last message.
        Outside this window, ONLY approved template messages may be sent.
        """
        if not last_inbound_msg_time:
            return False
        now = datetime.now(timezone.utc)
        t = last_inbound_msg_time.replace(tzinfo=timezone.utc) if last_inbound_msg_time.tzinfo is None else last_inbound_msg_time
        return (now - t) <= timedelta(hours=24)

    def prepare_outbound_message(
        self,
        recipient_phone: str,
        last_inbound_time: Optional[datetime],
        freeform_text: Optional[str] = None,
        template_name: Optional[str] = None,
        template_language: str = "en_US",
        template_components: Optional[list] = None
    ) -> Dict[str, Any]:
        within_window = self.can_send_freeform_message(last_inbound_time)

        if not within_window:
            if not template_name:
                raise WhatsApp24HourWindowViolation(
                    "24_HOUR_WINDOW_EXPIRED: Cannot send free-form message to guest. "
                    "An approved WhatsApp template message is required outside the 24-hour service window."
                )
            return {
                "messaging_product": "whatsapp",
                "to": recipient_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": template_language},
                    "components": template_components or []
                }
            }
        else:
            return {
                "messaging_product": "whatsapp",
                "to": recipient_phone,
                "type": "text",
                "text": {"body": freeform_text or ""}
            }

whatsapp_bsp = WhatsAppBusinessService()
