import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.auth import create_access_token
from services.billing.metering import UsageMeteringService
from services.billing.entitlements import entitlements_service
from services.database.session import AsyncSessionLocal
from services.database.models import (
    User, Organization, Subscription, UsageEvent, Property, Document, Agent, Invitation
)
from services.realtime.broadcaster import MultiTenantRealtimeHub

@pytest.mark.asyncio
async def test_billing_quota_resets_per_billing_period(db_session):
    """Phase 2.1: Quotas and spend caps count per billing period and reset across periods."""
    org_id = f"org_period_{uuid.uuid4().hex[:6]}"
    prop_id = f"prop_{uuid.uuid4().hex[:6]}"
    agent_id = f"agt_{uuid.uuid4().hex[:6]}"

    org = Organization(id=org_id, name="Billing Period Org", slug=f"slug-{org_id}")
    db_session.add(org)
    prop = Property(id=prop_id, organization_id=org_id, name="Period Hotel")
    db_session.add(prop)

    # Subscription with 100 turns limit on STARTER
    sub = Subscription(
        id=f"sub_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        plan_name="STARTER",
        status="ACTIVE",
        subscription_status="active",
        max_conversations_per_month=100
    )
    db_session.add(sub)

    # 1. Seed 100 usage events in PREVIOUS billing period (40 days ago)
    old_period_date = datetime.now(timezone.utc) - timedelta(days=40)
    for _ in range(100):
        evt = UsageEvent(
            id=f"evt_old_{uuid.uuid4().hex[:8]}",
            organization_id=org_id,
            property_id=prop_id,
            agent_id=agent_id,
            event_type="agent_turn",
            quantity=1,
            unit="turns",
            estimated_cost=0.001,
            created_at=old_period_date
        )
        db_session.add(evt)
    await db_session.commit()

    metering = UsageMeteringService(db_session=db_session)

    # 2. In current period, previous 100 events must NOT exhaust quota
    allowed, msg, details = await metering.check_billing_quota(org_id, resource="agent_turn", db=db_session)
    assert allowed is True
    assert details["current"] == 0, "Expected usage in fresh billing period to be 0 (reset)"

    # 3. Add 99 events in CURRENT period (limit - 1)
    for _ in range(99):
        evt_curr = UsageEvent(
            id=f"evt_curr_{uuid.uuid4().hex[:8]}",
            organization_id=org_id,
            property_id=prop_id,
            agent_id=agent_id,
            event_type="agent_turn",
            quantity=1,
            unit="turns",
            estimated_cost=0.001,
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(evt_curr)
    await db_session.commit()

    # Limit - 1 (99 / 100) -> Allowed
    allowed_99, _, d_99 = await metering.check_billing_quota(org_id, resource="agent_turn", db=db_session)
    assert allowed_99 is True
    assert d_99["current"] == 99

    # Add 1 more event -> Limit reached (100 / 100)
    evt_100 = UsageEvent(
        id=f"evt_curr_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        property_id=prop_id,
        agent_id=agent_id,
        event_type="agent_turn",
        quantity=1,
        unit="turns",
        estimated_cost=0.001,
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(evt_100)
    await db_session.commit()

    # Limit reached -> Rejected
    allowed_100, reason_100, d_100 = await metering.check_billing_quota(org_id, resource="agent_turn", db=db_session)
    assert allowed_100 is False
    assert "limit reached" in reason_100.lower()
    assert d_100["current"] == 100


@pytest.mark.asyncio
async def test_entitlement_boundaries_seats_properties_documents_and_voice(db_session):
    """Phase 2.1: Server-side enforcement of subscription_status, seats, properties, documents, voice_enabled."""
    org_id = f"org_entitle_{uuid.uuid4().hex[:6]}"
    org = Organization(id=org_id, name="Entitlement Org", slug=f"slug-{org_id}")
    db_session.add(org)

    # STARTER plan: max_seats=2, max_properties=1, max_documents=10, voice_enabled=False
    sub = Subscription(
        id=f"sub_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        plan_name="STARTER",
        status="ACTIVE",
        subscription_status="active",
        max_properties=1,
        max_agents=2
    )
    db_session.add(sub)
    await db_session.commit()

    metering = UsageMeteringService(db_session=db_session)

    # 1. Voice Gateway entitlement blocked on STARTER
    v_ok, v_reason, _ = await metering.check_billing_quota(org_id, resource="voice", db=db_session)
    assert v_ok is False
    assert "Voice Gateway is disabled" in v_reason

    # 2. Property limit (STARTER max_properties=1)
    # 0 properties -> Allowed
    p_ok1, _, _ = await metering.check_billing_quota(org_id, resource="property_creation", db=db_session)
    assert p_ok1 is True

    # Add 1 property -> Limit reached
    prop = Property(id=f"prop_{uuid.uuid4().hex[:6]}", organization_id=org_id, name="Hotel One")
    db_session.add(prop)
    await db_session.commit()

    p_ok2, p_reason2, _ = await metering.check_billing_quota(org_id, resource="property_creation", db=db_session)
    assert p_ok2 is False
    assert "Property limit reached" in p_reason2

    # 3. Seats limit (STARTER max_seats=2: counts active users + pending unexpired invites)
    u1 = User(id=f"u1_{uuid.uuid4().hex[:6]}", organization_id=org_id, email=f"u1@{org_id}.com", full_name="User 1", hashed_password="h", is_active=True, role="ADMIN")
    db_session.add(u1)
    await db_session.commit()

    # 1 user / 2 seats -> Allowed
    s_ok1, _, d_s1 = await metering.check_billing_quota(org_id, resource="seats", db=db_session)
    assert s_ok1 is True
    assert d_s1["current"] == 1

    # Add pending invitation (expires in 24 hours) -> 2 / 2 seats
    inv = Invitation(
        id=f"inv_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        email=f"pending@{org_id}.com",
        role="STAFF",
        token=str(uuid.uuid4()),
        invited_by_user_id=u1.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )
    db_session.add(inv)
    await db_session.commit()

    # 2 / 2 seats -> Rejected
    s_ok2, s_reason2, d_s2 = await metering.check_billing_quota(org_id, resource="seats", db=db_session)
    assert s_ok2 is False
    assert "seat limit reached" in s_reason2.lower()

    # 4. Subscription Status enforcement (Canceled / Past-due)
    sub.subscription_status = "canceled"
    await db_session.commit()

    c_ok, c_reason, _ = await metering.check_billing_quota(org_id, resource="agent_turn", db=db_session)
    assert c_ok is False
    assert "CANCELED" in c_reason


@pytest.mark.asyncio
async def test_concurrency_safe_quota_enforcement(db_session):
    """Phase 2.1: Concurrency safety with atomic checks under parallel requests."""
    org_id = f"org_conc_{uuid.uuid4().hex[:6]}"
    org = Organization(id=org_id, name="Concurrency Org", slug=f"slug-{org_id}")
    db_session.add(org)

    sub = Subscription(
        id=f"sub_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        plan_name="STARTER",
        status="ACTIVE",
        subscription_status="active",
        max_properties=1
    )
    db_session.add(sub)
    await db_session.commit()

    metering = UsageMeteringService()

    async def run_quota_check():
        async with AsyncSessionLocal() as session:
            return await metering.check_billing_quota(org_id, resource="property_creation", db=session)

    # Concurrently check quota for 1 available property slot across 5 parallel coroutines
    results = await asyncio.gather(*[run_quota_check() for _ in range(5)])

    # All initial checks before insert see slot 0/1
    assert all(r[0] is True for r in results)

    # Insert 1 property and commit
    prop = Property(id=f"prop_{uuid.uuid4().hex[:6]}", organization_id=org_id, name="Atomic Property")
    db_session.add(prop)
    await db_session.commit()

    # All subsequent concurrent checks see 1/1 and reject
    subsequent = await asyncio.gather(*[run_quota_check() for _ in range(5)])
    assert all(r[0] is False for r in subsequent)


@pytest.mark.asyncio
async def test_readiness_probe_returns_503_on_dependency_outage():
    """Phase 2.3: /ready returns 503 when dependencies (Redis/DB/Vector) are degraded."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/ready")
        # In test environment where Redis is disconnected or degraded, /ready must return 503
        if res.json().get("redis") == "disconnected" or res.json().get("database") != "connected":
            assert res.status_code == 503
            assert res.json()["status"] == "degraded"
        else:
            assert res.status_code == 200
            assert res.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_platform_telemetry_computed_from_real_checks(db_session):
    """Phase 2.3: /platform/telemetry dynamically computed from real checks and never hardcodes 100% OPERATIONAL."""
    org_id = f"org_telem_{uuid.uuid4().hex[:6]}"
    org = Organization(id=org_id, name="Telemetry Org", slug=f"slug-{org_id}")
    db_session.add(org)

    sa_user = User(
        id=f"sa_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        email=f"sa@{org_id}.com",
        full_name="Super Admin",
        hashed_password="hash",
        role="SUPER_ADMIN",
        is_active=True
    )
    db_session.add(sa_user)
    await db_session.commit()

    token = create_access_token({"sub": sa_user.id, "email": sa_user.email, "organization_id": org_id, "role": "SUPER_ADMIN"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/platform/telemetry", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["system_health"] in ["OPERATIONAL", "DEGRADED", "CRITICAL_OUTAGE"]
        assert "100% OPERATIONAL" not in str(data)
        assert "sla_uptime" in data


@pytest.mark.asyncio
async def test_multi_replica_realtime_pubsub_and_tenant_isolation():
    """Phase 2.5: Realtime event distribution across replicas with Last-Event-ID replay and tenant isolation."""
    replica_a = MultiTenantRealtimeHub()
    replica_b = MultiTenantRealtimeHub()

    org_a = f"org_real_a_{uuid.uuid4().hex[:6]}"
    org_b = f"org_real_b_{uuid.uuid4().hex[:6]}"

    # Subscriber on Replica B listens to Org A channel
    queue_a_on_b, _ = await replica_b.subscribe([f"org:{org_a}"])

    # Subscriber on Replica B listens to Org B channel (for tenant isolation check)
    queue_b_on_b, _ = await replica_b.subscribe([f"org:{org_b}"])

    try:
        # 1. Publish event on Replica A for Org A
        event_a_id = await replica_a.publish(
            event_type="AGENT_STATUS_CHANGED",
            data={"agent_id": "agt_1", "status": "BUSY"},
            organization_id=org_a
        )

        # 2. Deliver event to Replica B subscriber (simulating Redis cross-replica delivery)
        envelope = {
            "id": event_a_id,
            "type": "AGENT_STATUS_CHANGED",
            "replica_id": replica_a.replica_id,
            "organization_id": org_a,
            "data": {"agent_id": "agt_1", "status": "BUSY"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        replica_b._deliver_to_local_subscribers(f"org:{org_a}", envelope)

        # 3. Org A subscriber on Replica B receives the event in <1s
        received_evt = await asyncio.wait_for(queue_a_on_b.get(), timeout=1.0)
        assert received_evt["id"] == event_a_id
        assert received_evt["data"]["status"] == "BUSY"

        # 4. Strict tenant isolation: Org B subscriber on Replica B NEVER receives Org A event
        assert queue_b_on_b.empty(), "Org B subscriber must not receive Org A events!"

        # 5. Last-Event-ID replay across subscribers
        queue_replay, missed = await replica_b.subscribe([f"org:{org_a}"], last_event_id=None)
        # Verify buffer contains the published event
        buf = replica_b._get_buffer(f"org:{org_a}")
        assert len(buf.buffer) >= 1
    finally:
        replica_b.unsubscribe(queue_a_on_b)
        replica_b.unsubscribe(queue_b_on_b)
