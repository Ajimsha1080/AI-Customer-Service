import pytest
import uuid
import json
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding

from apps.api.main import app
from apps.api.config import settings
from apps.api.routers.email_webhooks import build_sns_canonical_string, SNS_CERT_CACHE
from services.security.email_service import email_service
from services.database.models import User, Organization, UserRole
from apps.api.auth import hash_password

@pytest.fixture(scope="module")
def rsa_key_and_cert():
    """Generates an RSA key and self-signed certificate for testing AWS SNS signatures."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Amazon Web Services"),
        x509.NameAttribute(NameOID.COMMON_NAME, "sns.us-east-1.amazonaws.com"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=10))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key, cert_pem

@pytest.fixture(scope="module")
def ecdsa_key():
    """Generates an ECDSA key for testing SendGrid signatures."""
    return ec.generate_private_key(ec.SECP256R1())

@pytest.mark.asyncio
async def test_h14_unauthenticated_email_webhooks_rejected(db_session):
    """H14: /bounce and /complaint reject unauthenticated requests with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Anonymous post to /bounce -> 401
        res1 = await ac.post("/api/v1/webhooks/email/bounce", json={"email": "victim@hotel.com"})
        assert res1.status_code == 401
        assert "Authentication required" in res1.json()["detail"]

        # Anonymous post to /complaint -> 401
        res2 = await ac.post("/api/v1/webhooks/email/complaint", json={"email": "victim@hotel.com"})
        assert res2.status_code == 401
        assert "Authentication required" in res2.json()["detail"]

@pytest.mark.asyncio
async def test_h14_aws_sns_signature_verification(db_session, rsa_key_and_cert):
    """H14: Valid AWS SNS cryptographic signature is accepted; forged/invalid cert URL is rejected with 401."""
    private_key, cert_pem = rsa_key_and_cert
    cert_url = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-123.pem"
    SNS_CERT_CACHE[cert_url] = cert_pem

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        target_email = f"bounced_{uuid.uuid4().hex[:6]}@guest.com"
        sns_msg = {
            "eventType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bouncedRecipients": [{"emailAddress": target_email, "diagnosticCode": "550 5.1.1 User unknown"}]
            }
        }
        sns_payload = {
            "Type": "Notification",
            "MessageId": str(uuid.uuid4()),
            "TopicArn": "arn:aws:sns:us-east-1:123456789012:ses-bounces",
            "Message": json.dumps(sns_msg),
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "SignatureVersion": "2",
            "SigningCertURL": cert_url
        }
        canonical_bytes = build_sns_canonical_string(sns_payload)
        signature = private_key.sign(canonical_bytes, padding.PKCS1v15(), hashes.SHA256())
        sns_payload["Signature"] = base64.b64encode(signature).decode("utf-8")

        headers = {
            "x-amz-sns-message-type": "Notification",
            "content-type": "application/json"
        }

        # 1. Valid AWS SNS notification succeeds (200) and suppresses target email
        res_valid = await ac.post("/api/v1/webhooks/email/bounce", headers=headers, json=sns_payload)
        assert res_valid.status_code == 200
        assert res_valid.json()["suppressed"] is True
        assert res_valid.json()["email"] == target_email
        assert email_service.is_suppressed(target_email) is True

        # 2. Forged cert URL from untrusted domain is rejected with 401
        forged_payload = sns_payload.copy()
        forged_payload["SigningCertURL"] = "https://evil-attacker.com/cert.pem"
        res_forged_url = await ac.post("/api/v1/webhooks/email/bounce", headers=headers, json=forged_payload)
        assert res_forged_url.status_code == 401

        # 3. Tampered payload is rejected with 401
        tampered_payload = sns_payload.copy()
        tampered_payload["Message"] = json.dumps({"eventType": "Bounce", "bounce": {"bouncedRecipients": [{"emailAddress": "other@guest.com"}]}})
        res_tampered = await ac.post("/api/v1/webhooks/email/bounce", headers=headers, json=tampered_payload)
        assert res_tampered.status_code == 401

@pytest.mark.asyncio
async def test_h14_sendgrid_ecdsa_signature_verification(db_session, ecdsa_key):
    """H14: Valid SendGrid ECDSA webhook signature is accepted; invalid signature is rejected with 401."""
    pub_key_pem = ecdsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")

    with patch.object(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", pub_key_pem):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            target_email = f"spam_{uuid.uuid4().hex[:6]}@guest.com"
            payload = {"email": target_email, "complaint_type": "spam"}
            raw_body = json.dumps(payload).encode("utf-8")
            timestamp = str(int(datetime.now(timezone.utc).timestamp()))

            signed_payload = timestamp.encode("utf-8") + raw_body
            sig = ecdsa_key.sign(signed_payload, ec.ECDSA(hashes.SHA256()))
            sig_b64 = base64.b64encode(sig).decode("utf-8")

            headers = {
                "x-twilio-email-event-webhook-signature": sig_b64,
                "x-twilio-email-event-webhook-timestamp": timestamp,
                "content-type": "application/json"
            }

            # Valid SendGrid signature succeeds and suppresses email
            res = await ac.post("/api/v1/webhooks/email/complaint", headers=headers, content=raw_body)
            assert res.status_code == 200
            assert res.json()["suppressed"] is True
            assert res.json()["email"] == target_email
            assert email_service.is_suppressed(target_email) is True

            # Invalid signature returns 401
            invalid_headers = headers.copy()
            invalid_headers["x-twilio-email-event-webhook-signature"] = base64.b64encode(b"invalid_signature").decode("utf-8")
            res_bad = await ac.post("/api/v1/webhooks/email/complaint", headers=invalid_headers, content=raw_body)
            assert res_bad.status_code == 401
