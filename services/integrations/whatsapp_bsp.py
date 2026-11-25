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
    def __init__(self, verify_token: Optional[str] = None, app_secret: Optional[str] = None):
        self._custom_verify_token = verify_token
        self._custom_app_secret = app_secret

    @property
    def verify_token(self) -> str:
        if self._custom_verify_token is not None:
            return self._custom_verify_token
        from apps.api.config import settings
        return settings.WHATSAPP_VERIFY_TOKEN or ""

    @property
    def app_secret(self) -> str:
        if self._custom_app_secret is not None:
            return self._custom_app_secret
        from apps.api.config import settings
        return settings.WHATSAPP_APP_SECRET or ""

    def verify_webhook_challenge(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Handles Meta webhook verification GET request."""
        if not self.verify_token:
            logger.warning("[WhatsApp] Webhook challenge failed: WHATSAPP_VERIFY_TOKEN is not configured.")
            return None
        if mode == "subscribe" and token and hmac.compare_digest(token, self.verify_token):
            logger.info("[WhatsApp] Webhook challenge verified successfully.")
            return challenge
        logger.warning(f"[WhatsApp] Webhook challenge failed (mode={mode}).")
        return None

    def verify_inbound_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verifies Meta X-Hub-Signature-256 header: 'sha256=<hex>'."""
        if not self.app_secret:
            logger.warning("[WhatsApp] Webhook signature verification failed: WHATSAPP_APP_SECRET is not configured.")
            return False
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        parts = signature_header.split("=", 1)
        if len(parts) != 2:
            return False
        provided_sig = parts[1]
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
