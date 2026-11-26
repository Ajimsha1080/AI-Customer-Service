import pytest
import asyncio
import uuid
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from services.database.session import AsyncSessionLocal
from services.database.models import User, Organization, Subscription, UsageEvent, UserRole, UserSession
from services.billing.metering import SaaSMeteringService
from services.billing.stripe_service import StripeBillingService
from apps.api.auth import create_access_token

async def setup_f6_tenant(plan_name="FREE", status="ACTIVE"):
    org_id = f"org_f6_{uuid.uuid4().hex[:6]}"
    user_id = f"user_f6_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as session:
        org = Organization(id=org_id, name="F6 Test Org", slug=f"f6-{uuid.uuid4().hex[:6]}", status="ACTIVE")
        session.add(org)

        user = User(
            id=user_id,
            organization_id=org_id,
            email=f"{user_id}@test.com",
            full_name="Billing Admin",
            hashed_password="hashed_pw_f6",
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True
        )
        session.add(user)

        sub = Subscription(
            id=f"sub_{uuid.uuid4().hex[:8]}",
            organization_id=org_id,
            plan_name=plan_name,
            status=status,
            subscription_status=status.lower(),
            stripe_customer_id=f"cus_{uuid.uuid4().hex[:8]}",
            stripe_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            max_conversations_per_month=100 if plan_name == "FREE" else 10000,
            max_agents=1 if plan_name == "FREE" else 5,
            max_properties=1 if plan_name == "FREE" else 2
        )
        session.add(sub)
        await session.commit()

    token = create_access_token(data={"sub": user_id, "org": org_id, "role": "admin"})
    async with AsyncSessionLocal() as session:
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        sess = UserSession(
            id=f"sess_f6_{uuid.uuid4().hex[:6]}",
            user_id=user_id,
            organization_id=org_id,
            session_token_hash=session_hash,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
        )
        session.add(sess)
        await session.commit()

    return {"org_id": org_id, "user_id": user_id, "token": token, "sub_id": sub.id, "stripe_sub_id": sub.stripe_subscription_id, "stripe_cus_id": sub.stripe_customer_id}

@pytest.mark.asyncio
async def test_f6_redis_usage_metering_and_postgres_sync():
    data = await setup_f6_tenant()
    org_id = data["org_id"]
    metering = SaaSMeteringService()

    # 1. Meter usage in Redis across LLM tokens, voice minutes, and WhatsApp messages
    tokens_total = await metering.record_usage_redis(org_id, "tokens", 2500, unit="tokens")
    voice_total = await metering.record_usage_redis(org_id, "voice_minutes", 15, unit="minutes")
    wa_total = await metering.record_usage_redis(org_id, "whatsapp_messages", 40, unit="messages")

    assert tokens_total == 2500
    assert voice_total == 15
    assert wa_total == 40

    # Verify pending Redis counts
    assert await metering.get_metered_usage_redis(org_id, "tokens") == 2500
    assert await metering.get_metered_usage_redis(org_id, "voice_minutes") == 15
    assert await metering.get_metered_usage_redis(org_id, "whatsapp_messages") == 40

    # 2. Sync Redis usage to PostgreSQL
    async with AsyncSessionLocal() as session:
        synced_count = await metering.sync_redis_usage_to_postgres(db=session)
        assert synced_count == 3

        # Verify records created in PostgreSQL UsageEvent table
        stmt = select(UsageEvent).where(UsageEvent.organization_id == org_id)
        res = await session.execute(stmt)
        events = res.scalars().all()
        assert len(events) == 3
        units = {e.unit for e in events}
        assert "tokens" in units
        assert "minutes" in units
        assert "messages" in units

    # Verify Redis counters reset after sync
    assert await metering.get_metered_usage_redis(org_id, "tokens") == 0
    assert await metering.get_metered_usage_redis(org_id, "voice_minutes") == 0
    assert await metering.get_metered_usage_redis(org_id, "whatsapp_messages") == 0

@pytest.mark.asyncio
async def test_f6_plan_limits_enforcement_402():
    # Free plan has 50 WhatsApp messages and 50,000 tokens
    data = await setup_f6_tenant(plan_name="FREE")
    org_id = data["org_id"]
    token = data["token"]
    metering = SaaSMeteringService()
    headers = {"Authorization": f"Bearer {token}"}

    # Within limits -> Check passes
    allowed, reason, _ = await metering.check_billing_quota(org_id, resource="whatsapp_messages")
    assert allowed is True

    # Exceed WhatsApp message limit in Redis
    await metering.record_usage_redis(org_id, "whatsapp_messages", 60)

    # Check must fail now
    allowed2, reason2, _ = await metering.check_billing_quota(org_id, resource="whatsapp_messages")
    assert allowed2 is False
    assert "quota exceeded" in reason2

    # HTTP endpoint returns 402 Payment Required
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/billing/check-quota",
            json={"organization_id": org_id, "resource": "whatsapp_messages"},
            headers=headers
        )
        assert res.status_code == 402
        assert "exceeded" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_f6_stripe_webhooks_lifecycle():
    data = await setup_f6_tenant(plan_name="STARTER")
    org_id = data["org_id"]
    from apps.api.config import settings

    import hmac
    def generate_stripe_header(payload_bytes: bytes, secret: str = settings.STRIPE_WEBHOOK_SECRET) -> str:
        timestamp = int(time.time())
        signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
        signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={signature}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unsigned webhook -> 400 Bad Request
        res_unsigned = await client.post("/api/v1/billing/webhook", content=b"{}")
        assert res_unsigned.status_code == 400

        # 2. Invalid signature -> 400 Bad Request
        res_invalid = await client.post(
            "/api/v1/billing/webhook",
            content=b'{"id": "evt_test_invalid"}',
            headers={"stripe-signature": "t=123,v1=invalid_sig"}
        )
        assert res_invalid.status_code == 400

        # 3. invoice.payment_failed -> Sets status to past_due with 7-day grace period
        evt_fail_id = f"evt_fail_{uuid.uuid4().hex[:6]}"
        payload_fail = json.dumps({
            "id": evt_fail_id,
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": data["stripe_cus_id"],
                    "subscription": data["stripe_sub_id"],
                    "status": "past_due"
                }
            }
        }).encode("utf-8")
        sig_fail = generate_stripe_header(payload_fail)

        res_fail = await client.post(
            "/api/v1/billing/webhook",
            content=payload_fail,
            headers={"stripe-signature": sig_fail, "Content-Type": "application/json"}
        )
        assert res_fail.status_code == 200

        # Verify DB subscription is now past_due with grace period
        async with AsyncSessionLocal() as session:
            stmt = select(Subscription).where(Subscription.organization_id == org_id)
            res = await session.execute(stmt)
            sub = res.scalar_one_or_none()
            assert sub.subscription_status == "past_due"
            assert sub.dunning_grace_period_until is not None
            grace_dt = sub.dunning_grace_period_until if sub.dunning_grace_period_until.tzinfo else sub.dunning_grace_period_until.replace(tzinfo=timezone.utc)
            assert grace_dt > datetime.now(timezone.utc)

        # 4. invoice.paid -> Restores active status and resets dunning count
        evt_paid_id = f"evt_paid_{uuid.uuid4().hex[:6]}"
        payload_paid = json.dumps({
            "id": evt_paid_id,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "customer": data["stripe_cus_id"],
                    "subscription": data["stripe_sub_id"],
                    "status": "active"
                }
            }
        }).encode("utf-8")
        sig_paid = generate_stripe_header(payload_paid)

        res_paid = await client.post(
            "/api/v1/billing/webhook",
            content=payload_paid,
            headers={"stripe-signature": sig_paid, "Content-Type": "application/json"}
        )
        assert res_paid.status_code == 200

        async with AsyncSessionLocal() as session:
            stmt = select(Subscription).where(Subscription.organization_id == org_id)
            res = await session.execute(stmt)
            sub = res.scalar_one_or_none()
            assert sub.subscription_status == "active"
            assert sub.dunning_attempt_count == 0
            assert sub.dunning_grace_period_until is None

        # 5. customer.subscription.deleted -> Sets status to canceled and downgrades to FREE
        evt_del_id = f"evt_del_{uuid.uuid4().hex[:6]}"
        payload_del = json.dumps({
            "id": evt_del_id,
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": data["stripe_cus_id"],
                    "subscription": data["stripe_sub_id"],
                    "status": "canceled"
                }
            }
        }).encode("utf-8")
        sig_del = generate_stripe_header(payload_del)

        res_del = await client.post(
            "/api/v1/billing/webhook",
            content=payload_del,
            headers={"stripe-signature": sig_del, "Content-Type": "application/json"}
        )
        assert res_del.status_code == 200

        async with AsyncSessionLocal() as session:
            stmt = select(Subscription).where(Subscription.organization_id == org_id)
            res = await session.execute(stmt)
            sub = res.scalar_one_or_none()
            assert sub.subscription_status == "canceled"
            assert sub.plan_name == "FREE"

@pytest.mark.asyncio
async def test_f6_dunning_grace_period_enforcement():
    data = await setup_f6_tenant(plan_name="STARTER", status="PAST_DUE")
    org_id = data["org_id"]
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}
    metering = SaaSMeteringService()

    # Case A: Within grace period (grace until tomorrow) -> Request permitted
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        stmt = select(Subscription).where(Subscription.organization_id == org_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()
        sub.subscription_status = "past_due"
        sub.dunning_grace_period_until = now + timedelta(days=2)
        await session.commit()

    allowed, reason, _ = await metering.check_billing_quota(org_id, resource="agent_turn")
    assert allowed is True

    # Case B: Grace period expired (grace ended yesterday) -> Request blocked (402)
    async with AsyncSessionLocal() as session:
        stmt = select(Subscription).where(Subscription.organization_id == org_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()
        sub.dunning_grace_period_until = now - timedelta(days=1)
        await session.commit()

    allowed2, reason2, _ = await metering.check_billing_quota(org_id, resource="agent_turn")
    assert allowed2 is False
    assert "grace period expired" in reason2.lower()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/billing/check-quota",
            json={"organization_id": org_id, "resource": "agent_turn"},
            headers=headers
        )
        assert res.status_code == 402
        assert "grace period expired" in res.json()["detail"].lower()
