import os
import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, Set
import httpx

logger = logging.getLogger("hospitality_agent_cloud.security.email")

# Email suppression list for bounces and complaints
_SUPPRESSED_EMAILS: Set[str] = set()

class EmailProviderBase:
    async def send(self, to_email: str, subject: str, text_content: str, html_content: str, sender: str) -> bool:
        raise NotImplementedError

class ConsoleEmailProvider(EmailProviderBase):
    async def send(self, to_email: str, subject: str, text_content: str, html_content: str, sender: str) -> bool:
        logger.info(f"[CONSOLE EMAIL] To: {to_email} | From: {sender} | Subject: {subject}\n{text_content}")
        return True

class SMTPEmailProvider(EmailProviderBase):
    def __init__(self, host: str, port: int, username: Optional[str] = None, password: Optional[str] = None, use_tls: bool = False, start_tls: bool = False):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.start_tls = start_tls

    async def send(self, to_email: str, subject: str, text_content: str, html_content: str, sender: str) -> bool:
        import aiosmtplib

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = to_email

        part1 = MIMEText(text_content, "plain", "utf-8")
        part2 = MIMEText(html_content, "html", "utf-8")
        message.attach(part1)
        message.attach(part2)

        client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            use_tls=self.use_tls,
            start_tls=self.start_tls,
            timeout=10
        )
        await client.connect()
        try:
            if self.username and self.password:
                await client.login(self.username, self.password)
            await client.send_message(message)
        finally:
            try:
                await client.quit()
            except Exception:
                pass

        logger.info(f"[SMTP] Dispatched email to {to_email} via {self.host}:{self.port}")
        return True

class SendGridEmailProvider(EmailProviderBase):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def send(self, to_email: str, subject: str, text_content: str, html_content: str, sender: str) -> bool:
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": sender},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_content},
                {"type": "text/html", "value": html_content}
            ]
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"[SendGrid] Failed to dispatch email: {resp.status_code} - {resp.text}")
                return False
        return True

class SESEmailProvider(EmailProviderBase):
    def __init__(self, region: str = "us-east-1"):
        self.region = region

    async def send(self, to_email: str, subject: str, text_content: str, html_content: str, sender: str) -> bool:
        import boto3
        ses = boto3.client("sesv2", region_name=self.region)
        loop = asyncio.get_running_loop()
        def _sync_send():
            return ses.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [to_email]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": text_content, "Charset": "UTF-8"},
                            "Html": {"Data": html_content, "Charset": "UTF-8"}
                        }
                    }
                }
            )
        await loop.run_in_executor(None, _sync_send)
        return True

class EmailDeliveryService:
    """Enterprise transactional email delivery service.
    Loads real HTML/plaintext templates from disk, selects configured provider,
    retries transient errors with exponential backoff, and suppresses bounced/complaint emails.
    """
    def __init__(self, template_dir: Optional[str] = None):
        if not template_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.template_dir = os.path.join(base_dir, "templates", "email")
        else:
            self.template_dir = template_dir

        self._provider_instance: Optional[EmailProviderBase] = None

    def _get_provider(self) -> EmailProviderBase:
        from apps.api.config import settings

        env = (getattr(settings, "ENVIRONMENT", "") or "").lower()
        provider_name = (getattr(settings, "EMAIL_SERVICE_PROVIDER", "") or "console").lower()

        if env in ("production", "prod") and provider_name in ("console", "mock"):
            raise RuntimeError("CRITICAL: EMAIL_SERVICE_PROVIDER cannot be 'console' in production environment.")

        if self._provider_instance is not None:
            return self._provider_instance

        if provider_name == "smtp":
            return SMTPEmailProvider(
                host=getattr(settings, "SMTP_HOST", "localhost"),
                port=int(getattr(settings, "SMTP_PORT", 1025)),
                username=getattr(settings, "SMTP_USER", None),
                password=getattr(settings, "SMTP_PASSWORD", None),
                use_tls=bool(getattr(settings, "SMTP_USE_TLS", False)),
                start_tls=bool(getattr(settings, "SMTP_STARTTLS", False))
            )
        elif provider_name == "sendgrid":
            return SendGridEmailProvider(api_key=getattr(settings, "SENDGRID_API_KEY", "") or "")
        elif provider_name == "ses":
            return SESEmailProvider(region=getattr(settings, "AWS_REGION", "us-east-1"))
        else:
            return ConsoleEmailProvider()

    def set_provider(self, provider: EmailProviderBase):
        """Allows injecting custom provider instances (e.g. SMTPEmailProvider for tests)."""
        self._provider_instance = provider

    def reset_provider(self):
        self._provider_instance = None

    def _render_template_file(self, filename: str, ctx: Dict[str, Any]) -> str:
        filepath = os.path.join(self.template_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for k, v in ctx.items():
                content = content.replace(f"{{{{ {k} }}}}", str(v))
                content = content.replace(f"{{{{{k}}}}}", str(v))
            return content
        # Fallback default content if template file is missing
        return str(ctx)

    def render_templates(self, template_name: str, ctx: Dict[str, Any]) -> tuple[str, str]:
        html_file = f"{template_name}.html"
        txt_file = f"{template_name}.txt"
        html_content = self._render_template_file(html_file, ctx)
        text_content = self._render_template_file(txt_file, ctx)
        return text_content, html_content

    async def send_email(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        template_context: Dict[str, Any],
        sender: Optional[str] = None,
        max_retries: int = 3
    ) -> bool:
        """Dispatches an email with retry logic and suppression checking."""
        clean_email = to_email.lower().strip()
        if clean_email in _SUPPRESSED_EMAILS:
            logger.warning(f"[EmailDelivery] Delivery skipped: {clean_email} is on suppression list (bounced/complaint).")
            return False

        from apps.api.config import settings
        from_email = sender or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@concierge-ai.com")

        text_body, html_body = self.render_templates(template_name, template_context)
        provider = self._get_provider()

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                success = await provider.send(
                    to_email=clean_email,
                    subject=subject,
                    text_content=text_body,
                    html_content=html_body,
                    sender=from_email
                )
                if success:
                    return True
            except Exception as e:
                last_error = e
                logger.warning(f"[EmailDelivery] Delivery attempt {attempt}/{max_retries} failed for {clean_email}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(0.1 * (2 ** (attempt - 1)))

        logger.error(f"[EmailDelivery] All {max_retries} delivery attempts failed for {clean_email}: {last_error}")
        return False

    def record_bounce(self, email: str, reason: str = "bounce"):
        """Adds email to suppression list."""
        clean = email.lower().strip()
        _SUPPRESSED_EMAILS.add(clean)
        logger.warning(f"[EmailDelivery] Recorded {reason} for {clean}; email suppressed from future dispatches.")

    def record_complaint(self, email: str):
        self.record_bounce(email, reason="complaint")

    def is_suppressed(self, email: str) -> bool:
        return email.lower().strip() in _SUPPRESSED_EMAILS

email_service = EmailDeliveryService()
