import pytest
import uuid
import json
import httpx
from datetime import datetime, timezone
from sqlalchemy import select

from apps.api.config import settings
from services.database.session import get_db, AsyncSessionLocal
from services.database.models import WebhookSubscription, WebhookDeliveryLog
from services.security.encryption import encrypt_value
from services.common.redis_service import get_redis_client
from services.integrations.webhooks import (
    dispatch_customer_webhook,
    verify_webhook_signature,
    generate_webhook_signature
)

@pytest.mark.asyncio
async def test_p11_webhook_delivery_success_with_hmac_signature():
    org_id = f"org_test_{uuid.uuid4().hex[:8]}"
    secret = "super_secret_webhook_key_12345"

    received_requests = []

    def mock_handler(request: httpx.Request):
        sig = request.headers.get("X-Hospitality-Signature")
        received_requests.append({
            "content": request.content,
            "signature": sig,
            "url": str(request.url)
        })
        return httpx.Response(status_code=200, json={"received": True})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_client = httpx.AsyncClient(transport=mock_transport)

    async with AsyncSessionLocal() as session:
        sub = WebhookSubscription(
            id=f"sub_{uuid.uuid4().hex[:12]}",
            organization_id=org_id,
            endpoint_url="https://api.partner.com/webhooks/hac",
            secret_encrypted=encrypt_value(secret, org_id=org_id),
            events=["reservation.created"],
            is_active=True
        )
        session.add(sub)
        await session.commit()

        payload = {"booking_id": "bkg_999", "status": "CONFIRMED"}
        log = await dispatch_customer_webhook(
            db=session,
            subscription=sub,
            event_type="reservation.created",
            payload_data=payload,
            http_client=mock_client
        )

        assert log.success is True
        assert log.status_code == 200
        assert log.attempt_count == 1
        assert len(received_requests) == 1

        # Verify HMAC signature received by destination
        req_info = received_requests[0]
        assert verify_webhook_signature(secret, req_info["content"], req_info["signature"]) is True

        # Verify Redis failure counter is reset to 0
        redis = await get_redis_client()
        if redis:
            val = await redis.get(f"webhook:failures:{sub.id}")
            assert val is None or int(val) == 0

@pytest.mark.asyncio
async def test_p11_webhook_delivery_exponential_backoff_and_retry():
    org_id = f"org_test_{uuid.uuid4().hex[:8]}"
    secret = "retry_secret_key_888"
    call_count = 0

    def mock_failing_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(status_code=500, json={"error": "temporary server failure"})
        return httpx.Response(status_code=200, json={"status": "recovered"})

    mock_transport = httpx.MockTransport(mock_failing_handler)
    mock_client = httpx.AsyncClient(transport=mock_transport)

    async with AsyncSessionLocal() as session:
        sub = WebhookSubscription(
            id=f"sub_{uuid.uuid4().hex[:12]}",
            organization_id=org_id,
            endpoint_url="https://api.flakey-endpoint.com/webhook",
            secret_encrypted=encrypt_value(secret, org_id=org_id),
            events=["guest.checked_in"],
            is_active=True
        )
        session.add(sub)
        await session.commit()

        log = await dispatch_customer_webhook(
            db=session,
            subscription=sub,
            event_type="guest.checked_in",
            payload_data={"guest_id": "gst_123"},
            max_retries=4,
            base_delay=0.005,
            http_client=mock_client
        )

        assert call_count == 3
        assert log.attempt_count == 3
        assert log.success is True
        assert log.status_code == 200

@pytest.mark.asyncio
async def test_p11_webhook_auto_pause_after_10_consecutive_failures():
    org_id = f"org_test_{uuid.uuid4().hex[:8]}"
    secret = "failure_secret_key_999"

    def always_fail_handler(request: httpx.Request):
        return httpx.Response(status_code=502, text="Bad Gateway")

    mock_transport = httpx.MockTransport(always_fail_handler)
    mock_client = httpx.AsyncClient(transport=mock_transport)

    sub_id = f"sub_fail_{uuid.uuid4().hex[:12]}"

    # Pre-set consecutive failures to 9 in Redis
    redis = await get_redis_client()
    if redis:
        await redis.set(f"webhook:failures:{sub_id}", 9)

    async with AsyncSessionLocal() as session:
        sub = WebhookSubscription(
            id=sub_id,
            organization_id=org_id,
            endpoint_url="https://dead-endpoint.com/webhook",
            secret_encrypted=encrypt_value(secret, org_id=org_id),
            events=["order.placed"],
            is_active=True
        )
        session.add(sub)
        await session.commit()

        log = await dispatch_customer_webhook(
            db=session,
            subscription=sub,
            event_type="order.placed",
            payload_data={"order_id": "ord_001"},
            max_retries=2,
            base_delay=0.001,
            http_client=mock_client
        )

        assert log.success is False
        assert log.attempt_count == 2
        assert log.status_code == 502

        # 10th consecutive failure triggers auto-pause
        if redis:
            failures = await redis.get(f"webhook:failures:{sub_id}")
            assert int(failures) == 10

        # Verify subscription was auto-paused
        stmt = select(WebhookSubscription).where(WebhookSubscription.id == sub_id)
        res = await session.execute(stmt)
        updated_sub = res.scalar_one()
        assert updated_sub.is_active is False

@pytest.mark.asyncio
async def test_p11_production_prohibits_fake_success(monkeypatch):
    org_id = f"org_prod_{uuid.uuid4().hex[:8]}"
    secret = "prod_secret_123"
    # Encrypt secret before setting prod env to avoid KMS ARN requirement
    encrypted_sec = encrypt_value(secret, org_id=org_id)

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    async with AsyncSessionLocal() as session:
        sub = WebhookSubscription(
            id=f"sub_prod_{uuid.uuid4().hex[:12]}",
            organization_id=org_id,
            endpoint_url="http://127.0.0.1:59999/unreachable_webhook_p11",
            secret_encrypted=encrypted_sec,
            events=["test.event"],
            is_active=True
        )
        session.add(sub)
        await session.commit()

        # In production, dispatching to unreachable endpoint MUST fail, not simulate success
        log = await dispatch_customer_webhook(
            db=session,
            subscription=sub,
            event_type="test.event",
            payload_data={"test": True},
            max_retries=1,
            base_delay=0.0
        )

        assert log.success is False
        assert log.status_code is None
        assert "Error:" in log.response_body
