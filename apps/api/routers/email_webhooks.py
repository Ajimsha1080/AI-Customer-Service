import logging
import base64
import json
import re
import secrets
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User
from services.security.email_service import email_service
from services.database.audit import record_audit_log_async

logger = logging.getLogger("hospitality_agent_cloud.webhooks.email")

router = APIRouter(prefix="/api/v1/webhooks/email", tags=["Email Webhooks"])

SNS_CERT_CACHE: Dict[str, bytes] = {}

def build_sns_canonical_string(data: dict) -> bytes:
    msg_type = data.get("Type")
    if msg_type == "Notification":
        fields = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        raise ValueError(f"Unknown SNS message type: {msg_type}")

    canonical = []
    for f in fields:
        if f in data and data[f] is not None:
            canonical.append(f"{f}\n{data[f]}\n")
    return "".join(canonical).encode("utf-8")

def verify_sns_cert_url(cert_url: str) -> bool:
    parsed = urlparse(cert_url)
    if parsed.scheme != "https":
        return False
    pattern = r"^sns\.[a-z0-9-]+\.amazonaws\.com$"
    if not re.match(pattern, parsed.hostname or ""):
        return False
    if not parsed.path.endswith(".pem"):
        return False
    return True

async def verify_aws_sns_signature(data: dict) -> bool:
    cert_url = data.get("SigningCertURL")
    signature_b64 = data.get("Signature")
    if not cert_url or not signature_b64:
        return False
    if not verify_sns_cert_url(cert_url):
        return False
    if settings.AWS_SNS_TOPIC_ARN and data.get("TopicArn") != settings.AWS_SNS_TOPIC_ARN:
        return False

    if cert_url in SNS_CERT_CACHE:
        cert_pem = SNS_CERT_CACHE[cert_url]
    else:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(cert_url)
            if resp.status_code != 200:
                return False
            cert_pem = resp.content
            SNS_CERT_CACHE[cert_url] = cert_pem

    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
        canonical_bytes = build_sns_canonical_string(data)
        sig_bytes = base64.b64decode(signature_b64)
        sig_version = str(data.get("SignatureVersion", "1"))
        hash_algo = hashes.SHA256() if sig_version == "2" else hashes.SHA1()
        public_key.verify(sig_bytes, canonical_bytes, padding.PKCS1v15(), hash_algo)
        return True
    except Exception as e:
        logger.warning(f"AWS SNS signature verification failed: {e}")
        return False

def verify_sendgrid_signature(raw_body: bytes, signature_b64: str, timestamp: str) -> bool:
    if not settings.SENDGRID_WEBHOOK_VERIFICATION_KEY:
        return False
    try:
        key_str = settings.SENDGRID_WEBHOOK_VERIFICATION_KEY.strip()
        if not key_str.startswith("-----BEGIN"):
            key_pem = f"-----BEGIN PUBLIC KEY-----\n{key_str}\n-----END PUBLIC KEY-----"
        else:
            key_pem = key_str
        public_key = load_pem_public_key(key_pem.encode("utf-8"))
        payload = timestamp.encode("utf-8") + raw_body
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception as e:
        logger.warning(f"SendGrid signature verification failed: {e}")
        return False

async def verify_email_webhook_auth(request: Request) -> Dict[str, Any]:
    """Authenticates email webhooks via AWS SNS signature, SendGrid ECDSA signature, or shared secret."""
    raw_body = await request.body()

    # 1. Check shared secret header if configured
    webhook_secret = request.headers.get("x-webhook-secret")
    if webhook_secret and settings.EMAIL_WEBHOOK_SECRET and secrets.compare_digest(webhook_secret, settings.EMAIL_WEBHOOK_SECRET):
        try:
            return json.loads(raw_body)
        except Exception:
            return {}

    # 2. Check AWS SNS headers
    if request.headers.get("x-amz-sns-message-type"):
        try:
            payload = json.loads(raw_body)
            valid = await verify_aws_sns_signature(payload)
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid AWS SNS cryptographic signature."
                )
            return payload
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Failed to verify AWS SNS signature: {e}"
            )

    # 3. Check SendGrid signature headers
    sg_sig = request.headers.get("x-twilio-email-event-webhook-signature")
    sg_ts = request.headers.get("x-twilio-email-event-webhook-timestamp")
    if sg_sig and sg_ts:
        if not verify_sendgrid_signature(raw_body, sg_sig, sg_ts):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid SendGrid webhook cryptographic signature."
            )
        try:
            return json.loads(raw_body)
        except Exception:
            return {}

    # Unauthenticated / unverified request rejected
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required: valid AWS SNS signature, SendGrid signature, or webhook secret required."
    )

class BounceWebhookPayload(BaseModel):
    email: str
    bounce_type: Optional[str] = "hard_bounce"
    reason: Optional[str] = None

class ComplaintWebhookPayload(BaseModel):
    email: str
    complaint_type: Optional[str] = "spam"
    reason: Optional[str] = None

@router.post("/bounce")
async def handle_bounce_webhook(
    request: Request,
    payload_data: Dict[str, Any] = Depends(verify_email_webhook_auth),
    db: AsyncSession = Depends(get_db)
):
    """Processes verified bounce webhooks from SES/SendGrid; suppresses future dispatches and updates user state."""
    # Extract email from direct payload or nested SNS SES Notification
    clean_email = None
    bounce_type = "hard_bounce"
    reason = None

    if "email" in payload_data:
        clean_email = str(payload_data["email"]).lower().strip()
        bounce_type = payload_data.get("bounce_type", "hard_bounce")
        reason = payload_data.get("reason")
    elif "Message" in payload_data:
        try:
            msg = json.loads(payload_data["Message"])
            recipients = msg.get("bounce", {}).get("bouncedRecipients", [])
            if recipients:
                clean_email = recipients[0].get("emailAddress", "").lower().strip()
                bounce_type = msg.get("bounce", {}).get("bounceType", "hard_bounce")
                reason = msg.get("bounce", {}).get("bouncedRecipients", [{}])[0].get("diagnosticCode")
        except Exception:
            pass

    if not clean_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not extract bounce email address.")

    email_service.record_bounce(clean_email, reason=bounce_type or "bounce")

    # Mark user email as unverified if registered
    stmt = select(User).where(User.email == clean_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user:
        user.email_verified = False
        await db.flush()
        await record_audit_log_async(
            org_id=user.organization_id,
            user_id=user.id,
            action="EMAIL_BOUNCED",
            target_type="user",
            target_id=user.id,
            details={"email": clean_email, "type": bounce_type, "reason": reason},
            db=db
        )

    return {"status": "recorded", "suppressed": True, "email": clean_email}

@router.post("/complaint")
async def handle_complaint_webhook(
    request: Request,
    payload_data: Dict[str, Any] = Depends(verify_email_webhook_auth),
    db: AsyncSession = Depends(get_db)
):
    """Processes verified spam complaint webhooks from SES/SendGrid; adds to suppression list."""
    clean_email = None
    complaint_type = "spam"
    reason = None

    if "email" in payload_data:
        clean_email = str(payload_data["email"]).lower().strip()
        complaint_type = payload_data.get("complaint_type", "spam")
        reason = payload_data.get("reason")
    elif "Message" in payload_data:
        try:
            msg = json.loads(payload_data["Message"])
            recipients = msg.get("complaint", {}).get("complainedRecipients", [])
            if recipients:
                clean_email = recipients[0].get("emailAddress", "").lower().strip()
                complaint_type = msg.get("complaint", {}).get("complaintFeedbackType", "spam")
        except Exception:
            pass

    if not clean_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not extract complaint email address.")

    email_service.record_complaint(clean_email)

    stmt = select(User).where(User.email == clean_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user:
        user.email_verified = False
        await db.flush()
        await record_audit_log_async(
            org_id=user.organization_id,
            user_id=user.id,
            action="EMAIL_SPAM_COMPLAINT",
            target_type="user",
            target_id=user.id,
            details={"email": clean_email, "type": complaint_type, "reason": reason},
            db=db
        )

    return {"status": "recorded", "suppressed": True, "email": clean_email}
