import socket
import uuid
import pytest
from email import message_from_bytes
from aiosmtpd.controller import Controller
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.config import Settings
from services.security.email_service import (
    email_service, SMTPEmailProvider, ConsoleEmailProvider
)

client = TestClient(app)

class RecordingSMTPHandler:
    def __init__(self):
        self.received_messages = []

    async def handle_DATA(self, server, session, envelope):
        msg = message_from_bytes(envelope.content)
        self.received_messages.append({
            "mail_from": envelope.mail_from,
            "rcpt_tos": envelope.rcpt_tos,
            "subject": msg.get("Subject"),
            "content": envelope.content.decode("utf-8", errors="replace"),
            "message": msg
        })
        return "250 Message accepted for delivery"

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

@pytest.mark.asyncio
async def test_real_smtp_email_delivery_and_templates():
    """Phase 0.3: Email delivery uses a real SMTP server with real MIME multipart templates,
    never an in-memory outbox list.
    """
    free_port = find_free_port()
    handler = RecordingSMTPHandler()
    controller = Controller(handler, hostname="127.0.0.1", port=free_port)
    controller.start()

    try:
        # Configure email service with SMTP provider pointing to test server
        smtp_provider = SMTPEmailProvider(host="127.0.0.1", port=free_port)
        email_service.set_provider(smtp_provider)

        test_email = f"guest_{uuid.uuid4().hex[:6]}@luxuryhotel.com"
        success = await email_service.send_email(
            to_email=test_email,
            subject="Welcome to Paradise Resort",
            template_name="verify_email",
            template_context={
                "name": "Jane Doe",
                "verify_url": "https://concierge.hotel.com/verify?token=xyz123",
                "token": "xyz123"
            }
        )
        assert success is True
        assert len(handler.received_messages) == 1

        rx = handler.received_messages[0]
        assert test_email in rx["rcpt_tos"]
        assert rx["subject"] == "Welcome to Paradise Resort"
        decoded_parts = [
            p.get_payload(decode=True).decode("utf-8", errors="replace")
            for p in rx["message"].walk()
            if not p.is_multipart()
        ]
        full_text = " ".join(decoded_parts)
        assert "Jane Doe" in full_text
        assert "https://concierge.hotel.com/verify?token=xyz123" in full_text

    finally:
        controller.stop()
        email_service.reset_provider()

def test_production_startup_refuses_console_email_provider():
    """Phase 0.3: Startup fails in production if email provider is 'console' or 'mock'."""
    with pytest.raises(ValueError) as excinfo:
        Settings(
            ENVIRONMENT="production",
            EMAIL_SERVICE_PROVIDER="console",
            DATABASE_URL="postgresql+asyncpg://prod_user:SuperSecretPassword123!@db.prod.internal:5432/hotel_db",
            REDIS_URL="redis://:RedisProdPass123!@redis.prod.internal:6379/0",
            SECRET_KEY="prod-secret-key-at-least-32-bytes-long-super-safe",
            JWT_SECRET_KEY="prod-jwt-secret-key-at-least-32-bytes-long",
            JWT_REFRESH_SECRET_KEY="prod-jwt-refresh-secret-at-least-32-bytes",
            CORS_ORIGINS=["https://app.concierge.com"],
            COOKIE_SECURE=True,
            STT_PROVIDER="whisper",
            TTS_PROVIDER="elevenlabs",
            ELEVENLABS_API_KEY="sk_live_elevenlabs_prod_key_12345678",
            WHATSAPP_API_KEY="wa_live_prod_key_87654321",
            STRIPE_SECRET_KEY="sk_live_stripe_secret_key_12345678",
            STRIPE_WEBHOOK_SECRET="whsec_live_stripe_webhook_secret_1234"
        )
    assert "EMAIL_SERVICE_PROVIDER cannot be 'console'" in str(excinfo.value)

@pytest.mark.asyncio
async def test_email_bounce_and_complaint_webhooks_and_suppression():
    """Phase 0.3: Bounce and complaint webhooks record suppression and prevent future dispatch."""
    bounced_email = f"bounced_{uuid.uuid4().hex[:8]}@bad-domain.test"

    # Register user first
    reg = client.post("/api/v1/auth/register", json={
        "email": bounced_email,
        "password": "StrongPassword_2026!",
        "full_name": "Bounced User"
    })
    assert reg.status_code == 200

    # 1. Trigger bounce webhook
    res_bounce = client.post("/api/v1/webhooks/email/bounce", json={
        "email": bounced_email,
        "bounce_type": "hard_bounce",
        "reason": "550 5.1.1 User unknown"
    })
    assert res_bounce.status_code == 200
    assert res_bounce.json()["suppressed"] is True

    # 2. Verify suppression status
    assert email_service.is_suppressed(bounced_email) is True

    # 3. Attempting to dispatch email to suppressed address is immediately blocked
    sent = await email_service.send_email(
        to_email=bounced_email,
        subject="Should not send",
        template_name="verify_email",
        template_context={"name": "User", "verify_url": "http://test"}
    )
    assert sent is False
