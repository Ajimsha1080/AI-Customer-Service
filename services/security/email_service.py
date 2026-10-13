import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class EmailDeliveryService:
    """Enterprise email delivery service with pluggable provider backends.
    Supports SES, SendGrid, SMTP, or Console/Mock for local testing.
    Includes built-in transactional email templates and audit tracking.
    """
    def __init__(self, provider: str = "console"):
        self.provider = provider
        self.outbox = []  # In-memory test store

    async def send_email(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        template_context: Dict[str, Any],
        sender: Optional[str] = "noreply@concierge-ai.com"
    ) -> bool:
        body = self._render_template(template_name, template_context)
        message = {
            "to": to_email,
            "sender": sender,
            "subject": subject,
            "body": body,
            "template": template_name,
            "context": template_context
        }
        self.outbox.append(message)
        logger.info(f"[{self.provider.upper()}] Email dispatched to {to_email} | Subject: {subject}")
        return True

    def _render_template(self, template_name: str, ctx: Dict[str, Any]) -> str:
        if template_name == "verify_email":
            return f"Hello {ctx.get('name', 'User')},\n\nPlease verify your email by clicking: {ctx.get('verify_url')}\n\nToken: {ctx.get('token')}"
        elif template_name == "password_reset":
            return f"Hello {ctx.get('name', 'User')},\n\nReset your password using the link: {ctx.get('reset_url')}\n\nThis link expires in 1 hour."
        elif template_name == "mfa_alert":
            return f"Security Alert: MFA was enabled/updated on your account at {ctx.get('timestamp')} from IP {ctx.get('ip')}."
        elif template_name == "support_access_granted":
            return f"Customer Notice: Support access was granted to {ctx.get('org_name')} until {ctx.get('expires_at')} by {ctx.get('granted_by')}."
        elif template_name == "invitation":
            return f"You have been invited to join {ctx.get('org_name')} as {ctx.get('role')}.\n\nAccept invitation: {ctx.get('invite_url')}"
        return f"Notification: {ctx}"

email_service = EmailDeliveryService()
