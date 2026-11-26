import pytest
import uuid
import json
import base64
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
import pyotp

from apps.api.main import app
from apps.api.config import settings, Settings
from services.security.encryption import (
    EnvelopeEncryptionService,
    encrypt_value,
    decrypt_value
)
from services.database.models import User, Organization, UserRole, SSOConfig, WebhookSubscription
from services.integrations.webhooks import dispatch_customer_webhook

def test_h9_aws_kms_envelope_encryption_flow():
    """H9: Real AWS KMS envelope encryption uses generate_data_key and decrypt."""
    svc = EnvelopeEncryptionService()
    
    mock_kms = MagicMock()
    # 32-byte raw DEK
    raw_dek = b"\x01" * 32
    encrypted_dek_blob = b"kms_encrypted_ciphertext_blob_bytes_xyz"
    
    mock_kms.generate_data_key.return_value = {
        "Plaintext": raw_dek,
        "CiphertextBlob": encrypted_dek_blob
    }
    mock_kms.decrypt.return_value = {
        "Plaintext": raw_dek
    }
    svc._kms_client = mock_kms

    kms_arn = "arn:aws:kms:us-east-1:111122223333:key/mrk-12345678"
    secret_text = "HighlyConfidentialSecret123"

    # Encrypt
    envelope = svc.encrypt(secret_text, kms_arn=kms_arn)
    assert envelope.startswith("env:")
    assert secret_text not in envelope

    # Verify KMS generate_data_key was called with the ARN
    mock_kms.generate_data_key.assert_called_once_with(
        KeyId=kms_arn,
        KeySpec="AES_256"
    )

    # Decrypt
    decrypted = svc.decrypt(envelope)
    assert decrypted == secret_text
    mock_kms.decrypt.assert_called_once_with(
        CiphertextBlob=encrypted_dek_blob
    )

def test_h9_byok_kms_arn_tenant_isolation():
    """H9: Tenant BYOK stored as KMS ARN in DB/Redis enforces cross-tenant boundary."""
    svc = EnvelopeEncryptionService()
    
    mock_kms = MagicMock()
    raw_dek = b"\x02" * 32
    mock_kms.generate_data_key.return_value = {
        "Plaintext": raw_dek,
        "CiphertextBlob": b"blob_tenant_a"
    }
    mock_kms.decrypt.return_value = {
        "Plaintext": raw_dek
    }
    svc._kms_client = mock_kms

    tenant_a_org_id = f"org_a_{uuid.uuid4().hex[:6]}"
    tenant_b_org_id = f"org_b_{uuid.uuid4().hex[:6]}"
    
    tenant_a_arn = "arn:aws:kms:us-east-1:111122223333:key/tenant-a-key"
    tenant_b_arn = "arn:aws:kms:us-east-1:111122223333:key/tenant-b-key"

    svc.register_tenant_byok_arn(tenant_a_org_id, tenant_a_arn)
    svc.register_tenant_byok_arn(tenant_b_org_id, tenant_b_arn)

    envelope_a = svc.encrypt("Tenant A Secret Data", org_id=tenant_a_org_id)
    assert envelope_a.startswith("env:")
    mock_kms.generate_data_key.assert_called_with(KeyId=tenant_a_arn, KeySpec="AES_256")

    # Decrypting as Tenant A succeeds
    assert svc.decrypt(envelope_a, org_id=tenant_a_org_id) == "Tenant A Secret Data"

    # Decrypting Tenant A's envelope with Tenant B's org context is rejected
    with pytest.raises(ValueError) as exc:
        svc.decrypt(envelope_a, org_id=tenant_b_org_id)
    assert "BYOK KMS ARN mismatch" in str(exc.value)

def test_h9_production_fails_without_kms():
    """H9: Production fails at startup if KMS is not configured."""
    with pytest.raises(ValueError) as exc:
        Settings(
            ENVIRONMENT="production",
            KMS_PRIMARY_KEY_ID=None,
            SECRET_KEY="a" * 64,
            JWT_SECRET_KEY="b" * 64,
            JWT_REFRESH_SECRET_KEY="c" * 64,
            DATABASE_URL="postgresql+asyncpg://app_user:pwd@db:5432/hac",
            REDIS_URL="redis://redis:6379/0",
            STRIPE_SECRET_KEY="sk_live_12345",
            STRIPE_WEBHOOK_SECRET="whsec_12345",
            STRIPE_PRICE_STARTER="price_starter_live",
            STRIPE_PRICE_PROFESSIONAL="price_pro_live",
            STRIPE_PRICE_BUSINESS="price_biz_live",
            STRIPE_PRICE_ENTERPRISE="price_ent_live",
            OPENAI_API_KEY="sk-live-openai",
            WHATSAPP_APP_SECRET="d" * 32,
            WHATSAPP_VERIFY_TOKEN="e" * 16,
            WHATSAPP_API_KEY=None,
            CORS_ORIGINS=["https://app.concierge-ai.com"],
            EMAIL_SERVICE_PROVIDER="sendgrid",
            SENDGRID_API_KEY="SG.12345"
        )
    assert "KMS_PRIMARY_KEY_ID must be configured" in str(exc.value)

@pytest.mark.asyncio
async def test_h9_mfa_secret_encrypted_at_rest(db_session):
    """H9: users.mfa_secret is encrypted at rest in DB and decrypted during TOTP verification."""
    org_id = str(uuid.uuid4())
    org = Organization(id=org_id, name="KMS MFA Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
    raw_totp_secret = pyotp.random_base32()

    user = User(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        email=f"kms_mfa_{uuid.uuid4().hex[:6]}@hotel.com",
        full_name="MFA User",
        hashed_password="hashed_pwd",
        role=UserRole.STAFF,
        is_active=True,
        mfa_enabled=True,
        mfa_secret=encrypt_value(raw_totp_secret, org_id=org_id)
    )
    db_session.add(org)
    db_session.add(user)
    await db_session.commit()

    # Verify column in database is encrypted
    assert user.mfa_secret.startswith("env:")
    assert raw_totp_secret not in user.mfa_secret

    # Verify decrypt_value recovers original TOTP secret
    decrypted_secret = decrypt_value(user.mfa_secret, org_id=org_id)
    assert decrypted_secret == raw_totp_secret

    # Verify pyotp matches TOTP generated with original secret
    totp = pyotp.TOTP(decrypted_secret)
    valid_code = totp.now()
    assert totp.verify(valid_code)

@pytest.mark.asyncio
async def test_h9_webhook_secret_encrypted_at_rest(db_session):
    """H9: webhook_subscriptions.secret_encrypted is encrypted at rest and decrypted on dispatch."""
    org_id = str(uuid.uuid4())
    org = Organization(id=org_id, name="KMS Webhook Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
    raw_secret = "raw_webhook_hmac_secret_9999"

    sub = WebhookSubscription(
        id=f"whsub_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        endpoint_url="https://example.com/webhook",
        secret_encrypted=encrypt_value(raw_secret, org_id=org_id),
        events=["reservation.created"],
        is_active=True
    )
    db_session.add(org)
    db_session.add(sub)
    await db_session.commit()

    # Column is encrypted
    assert sub.secret_encrypted.startswith("env:")
    assert raw_secret not in sub.secret_encrypted

    # Webhook dispatch decrypts secret to create HMAC
    log = await dispatch_customer_webhook(
        db=db_session,
        subscription=sub,
        event_type="reservation.created",
        payload_data={"guest": "VIP"}
    )
    assert log is not None
    assert log.organization_id == org_id
