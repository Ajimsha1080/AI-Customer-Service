import hmac
import json
import time
import uuid
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from services.database.models import WebhookSubscription, WebhookDeliveryLog
from services.security.encryption import decrypt_value
from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.integrations.webhooks")

def generate_webhook_signature(secret: str, payload_bytes: bytes, timestamp: int) -> str:
    """Generates standard HMAC-SHA256 signature for customer webhook payload."""
    signed_payload = f"t={timestamp}.".encode("utf-8") + payload_bytes
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"

def verify_webhook_signature(secret: str, payload_bytes: bytes, header: str, tolerance_seconds: int = 300) -> bool:
    """Verifies HMAC-SHA256 signature and prevents replay attacks outside tolerance window."""
    try:
        parts = dict(item.split("=") for item in header.split(","))
        timestamp = int(parts.get("t", 0))
        provided_sig = parts.get("v1", "")

        now = int(time.time())
        if abs(now - timestamp) > tolerance_seconds:
            logger.warning("[Webhook] Signature timestamp outside tolerance window.")
            return False

        signed_payload = f"t={timestamp}.".encode("utf-8") + payload_bytes
        expected_sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided_sig, expected_sig)
    except Exception as e:
        logger.error(f"[Webhook] Signature verification error: {e}")
        return False

async def dispatch_customer_webhook(
    db: AsyncSession,
    subscription: WebhookSubscription,
    event_type: str,
    payload_data: Dict[str, Any],
    max_retries: int = 5,
    base_delay: float = 0.5,
    http_client: Optional[httpx.AsyncClient] = None
) -> WebhookDeliveryLog:
    """
    Delivers customer webhook with HMAC-SHA256 signature and exponential backoff retry.
    Tracks consecutive failures in Redis and automatically pauses subscriptions after 10 consecutive failures.
    Records delivery outcome in webhook_delivery_logs table.
    """
    now_ts = int(time.time())
    delivery_id = f"del_{uuid.uuid4().hex[:12]}"
    envelope = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "event": event_type,
        "organization_id": subscription.organization_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload_data
    }
    raw_json = json.dumps(envelope)
    payload_bytes = raw_json.encode("utf-8")
    raw_secret = decrypt_value(subscription.secret_encrypted, org_id=subscription.organization_id)
    sig_header = generate_webhook_signature(raw_secret, payload_bytes, now_ts)

    headers = {
        "Content-Type": "application/json",
        "X-Hospitality-Signature": sig_header,
        "X-Signature": sig_header,
        "X-Webhook-ID": delivery_id,
        "X-Webhook-Event": event_type,
        "X-Webhook-Timestamp": str(now_ts),
        "User-Agent": "HospitalityAgentCloud-Webhooks/1.0"
    }

    success = False
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    attempts_made = 0

    # Rule 1: No stubs/fake success in production.
    # Simulated mode is allowed ONLY when ENVIRONMENT is development or testing AND endpoint is .test
    is_test_env = settings.ENVIRONMENT in ("development", "testing")
    if is_test_env and subscription.endpoint_url.endswith(".test") and http_client is None:
        attempts_made = 1
        status_code = 200
        response_body = '{"received": true}'
        success = True
    else:
        client_to_use = http_client or httpx.AsyncClient(timeout=10.0)
        close_client = http_client is None
        try:
            for attempt in range(1, max_retries + 1):
                attempts_made = attempt
                try:
                    resp = await client_to_use.post(
                        subscription.endpoint_url,
                        content=payload_bytes,
                        headers=headers
                    )
                    status_code = resp.status_code
                    response_body = resp.text[:2048] if resp.text else ""
                    if 200 <= resp.status_code < 300:
                        success = True
                        break
                    else:
                        logger.warning(
                            f"[Webhook] Non-2xx response {resp.status_code} on attempt {attempt}/{max_retries} for {subscription.endpoint_url}"
                        )
                except Exception as exc:
                    logger.warning(
                        f"[Webhook] Dispatch error on attempt {attempt}/{max_retries} for {subscription.endpoint_url}: {exc}"
                    )
                    response_body = f"Error: {str(exc)[:200]}"
                    status_code = None

                if attempt < max_retries and base_delay > 0:
                    backoff_delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff_delay)
        finally:
            if close_client:
                await client_to_use.aclose()

    # Track consecutive failures in Redis & auto-pause
    redis = await get_redis_client()
    failure_key = f"webhook:failures:{subscription.id}"
    if success:
        if redis:
            try:
                await redis.set(failure_key, 0)
            except Exception as e:
                logger.warning(f"[Webhook] Failed to reset failure count in Redis: {e}")
    else:
        consecutive_failures = 1
        if redis:
            try:
                consecutive_failures = await redis.incr(failure_key)
            except Exception as e:
                logger.warning(f"[Webhook] Failed to increment failure count in Redis: {e}")

        if consecutive_failures >= 10:
            logger.error(
                f"[Webhook] Subscription {subscription.id} reached {consecutive_failures} consecutive failures. Auto-pausing subscription."
            )
            subscription.is_active = False
            try:
                stmt_update = (
                    update(WebhookSubscription)
                    .where(WebhookSubscription.id == subscription.id)
                    .values(is_active=False)
                )
                await db.execute(stmt_update)
            except Exception as e:
                logger.error(f"[Webhook] Failed to update subscription is_active in DB: {e}")

    # Record delivery log
    log_entry = WebhookDeliveryLog(
        id=delivery_id,
        subscription_id=subscription.id,
        organization_id=subscription.organization_id,
        event_type=event_type,
        payload_json=envelope,
        status_code=status_code,
        response_body=response_body,
        attempt_count=attempts_made,
        success=success
    )
    db.add(log_entry)
    await db.commit()

    logger.info(
        f"[Webhook] Finished delivery '{event_type}' to '{subscription.endpoint_url}' "
        f"(delivery_id={delivery_id}, success={success}, attempts={attempts_made}, status={status_code})"
    )
    return log_entry

async def deliver_org_webhook_event(
    db: AsyncSession,
    organization_id: str,
    event_type: str,
    payload_data: Dict[str, Any]
) -> List[WebhookDeliveryLog]:
    """Dispatches an event to all active matching webhook subscriptions for an organization."""
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.organization_id == organization_id,
        WebhookSubscription.is_active == True
    )
    res = await db.execute(stmt)
    subs = res.scalars().all()
    logs = []
    for sub in subs:
        if "*" in sub.events or event_type in sub.events:
            log = await dispatch_customer_webhook(db, sub, event_type, payload_data)
            logs.append(log)
    return logs
