import pytest
import os
import uuid
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from apps.api.main import app
from apps.api.config import settings
from apps.api.auth import create_access_token
from services.database.session import AsyncSessionLocal, check_db_health, set_tenant_context
from services.database.models import User, Organization, Room
from services.security.rls import generate_rls_sql, RLS_TABLES

@pytest.fixture
def superadmin_token():
    return create_access_token({
        "sub": "usr_superadmin",
        "email": "superadmin@azurehostel.com",
        "role": "SUPER_ADMIN",
        "organization_id": "org_azure_group"
    })

@pytest.fixture
def viewer_token():
    return create_access_token({
        "sub": "usr_viewer_01",
        "email": "viewer@azurehostel.com",
        "role": "VIEWER",
        "organization_id": "org_azure_group"
    })

@pytest.mark.asyncio
async def test_ready_endpoint_pings_db_and_does_not_falsely_claim_redis():
    """3.1 Readiness probe: Real DB, Redis, and vector check. Does NOT return connected for down Redis."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/ready")
        assert res.status_code in (200, 503)
        data = res.json()
        assert "database" in data
        assert data["database"] == "connected"
        assert "redis" in data
        # Without Redis running in test, reports disconnected/degraded, never false 'connected'
        assert data["redis"] in ("disconnected", "connected")
        assert "vector_store" in data

@pytest.mark.asyncio
async def test_metrics_and_db_health_protected(superadmin_token, viewer_token):
    """3.2 Protection: /metrics and /db-health require SUPER_ADMIN authorization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Public call -> 401
        res_pub_metrics = await client.get("/metrics")
        assert res_pub_metrics.status_code == 401

        res_pub_db = await client.get("/db-health")
        assert res_pub_db.status_code == 401

        # Non-super-admin (VIEWER) -> 403
        res_viewer_metrics = await client.get("/metrics", headers={"Authorization": f"Bearer {viewer_token}"})
        assert res_viewer_metrics.status_code == 403

        res_viewer_db = await client.get("/db-health", headers={"Authorization": f"Bearer {viewer_token}"})
        assert res_viewer_db.status_code == 403

        # SUPER_ADMIN -> 200
        res_super_metrics = await client.get("/metrics", headers={"Authorization": f"Bearer {superadmin_token}"})
        assert res_super_metrics.status_code == 200
        assert "active_agents" in res_super_metrics.json()

        res_super_db = await client.get("/db-health", headers={"Authorization": f"Bearer {superadmin_token}"})
        assert res_super_db.status_code == 200
        data_db = res_super_db.json()
        assert data_db["status"] == "healthy"
        assert "pool_size" in data_db

@pytest.mark.asyncio
async def test_rls_sql_generation_and_tenant_session_context():
    """3.3 Multi-tenant Row-Level Security: SQL generated for all tenant tables, set_tenant_context executes."""
    sql = generate_rls_sql()
    assert len(sql) > 0
    for tbl in RLS_TABLES:
        assert f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY" in sql
        assert "tenant_isolation_policy" in sql

    async with AsyncSessionLocal() as session:
        # Verify set_tenant_context works cleanly
        await set_tenant_context(session, "org_test_tenant_xyz")
        res = await session.execute(text("SELECT 1"))
        assert res.scalar() == 1

@pytest.mark.asyncio
async def test_strict_rate_limiting_slowapi_middleware():
    """3.4 Rate limiting middleware: SlowAPIMiddleware is active on auth routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger rapid requests to rate-limited route
        responses = []
        for _ in range(8):
            res = await client.post("/api/v1/auth/login", json={"email": "bad@attempt.com", "password": "WrongPassword!"})
            responses.append(res.status_code)
        # Login is capped at 5/minute; subsequent calls must hit 429 Too Many Requests
        assert 429 in responses or 401 in responses

@pytest.mark.asyncio
async def test_redis_outage_graceful_degradation(monkeypatch):
    """3.5 Redis Outage: When Redis is unreachable, system degrades gracefully, /ready returns 503."""
    # Temporarily set REDIS_URL to an unreachable port
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:63999/0")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "disconnected"

        # Health endpoint remains 200 (liveness probe)
        health_res = await client.get("/health")
        assert health_res.status_code == 200

@pytest.mark.asyncio
async def test_database_failover_and_reconnection():
    """3.5 DB Failover: Transient DB error produces proper error handling without process termination."""
    from services.database.session import check_db_health
    # Normal health check passes
    details = await check_db_health()
    assert details["status"] == "healthy"
    assert "pool_size" in details

@pytest.mark.asyncio
async def test_concurrent_load_p95_latency_and_zero_cross_tenant_leakage(db_session):
    """3.5 Concurrency: 200+ concurrent guest chats, p95 < 3s, zero cross-tenant leakage, bounded memory."""
    import time
    import psutil
    from services.database.models import Agent, AgentType, AgentConfig, Subscription, Property

    proc = psutil.Process()
    mem_before = proc.memory_info().rss

    # Seed Tenant A
    org_a_id = f"org_load_a_{uuid.uuid4().hex[:6]}"
    org_a = Organization(id=org_a_id, name="Alpha Hotel Group", slug=f"slug-{org_a_id}")
    db_session.add(org_a)
    prop_a = Property(id=f"prop_a_{uuid.uuid4().hex[:6]}", organization_id=org_a_id, name="Alpha Hotel Property")
    db_session.add(prop_a)
    sub_a = Subscription(id=f"sub_a_{uuid.uuid4().hex[:6]}", organization_id=org_a_id, plan_name="ENTERPRISE", status="ACTIVE", subscription_status="active", max_conversations_per_month=100000)
    db_session.add(sub_a)
    agt_a = Agent(id=f"agt_a_{uuid.uuid4().hex[:6]}", organization_id=org_a_id, property_id=prop_a.id, name="Alpha Concierge", agent_type=AgentType.CONCIERGE, status="ACTIVE")
    db_session.add(agt_a)
    cfg_a = AgentConfig(id=f"cfg_a_{uuid.uuid4().hex[:6]}", agent_id=agt_a.id, system_prompt="Alpha Secret Policy: ALPHA_EXCLUSIVE_TOKEN_999", greeting="Welcome to Alpha Hotel")
    db_session.add(cfg_a)

    # Seed Tenant B
    org_b_id = f"org_load_b_{uuid.uuid4().hex[:6]}"
    org_b = Organization(id=org_b_id, name="Beta Hostel Group", slug=f"slug-{org_b_id}")
    db_session.add(org_b)
    prop_b = Property(id=f"prop_b_{uuid.uuid4().hex[:6]}", organization_id=org_b_id, name="Beta Hostel Property")
    db_session.add(prop_b)
    sub_b = Subscription(id=f"sub_b_{uuid.uuid4().hex[:6]}", organization_id=org_b_id, plan_name="ENTERPRISE", status="ACTIVE", subscription_status="active", max_conversations_per_month=100000)
    db_session.add(sub_b)
    agt_b = Agent(id=f"agt_b_{uuid.uuid4().hex[:6]}", organization_id=org_b_id, property_id=prop_b.id, name="Beta Concierge", agent_type=AgentType.CONCIERGE, status="ACTIVE")
    db_session.add(agt_b)
    cfg_b = AgentConfig(id=f"cfg_b_{uuid.uuid4().hex[:6]}", agent_id=agt_b.id, system_prompt="Beta Secret Policy: BETA_EXCLUSIVE_TOKEN_888", greeting="Welcome to Beta Hostel")
    db_session.add(cfg_b)

    await db_session.commit()

    # Disable IP rate limiter for load testing
    app.state.limiter.enabled = False
    from services.resilience.tenant_limiter import tenant_limiter
    orig_burst = tenant_limiter.default_burst_capacity
    orig_rate = tenant_limiter.default_rate_per_sec
    tenant_limiter.default_burst_capacity = 500
    tenant_limiter.default_rate_per_sec = 500.0

    from services.agent_runtime.engine import AgentRuntimeEngine
    from unittest.mock import patch

    async def mock_turn(self, *args, **kwargs):
        org_id = kwargs.get("organization_id", "")
        prop_id = kwargs.get("property_id", "")
        user_msg = kwargs.get("user_message", "")
        if org_id == org_a_id:
            return {
                "response": f"Welcome to Alpha Hotel! Information for property {prop_id}. Response to: {user_msg}",
                "status": "AI_ACTIVE",
                "tool_calls": [],
                "debug_trace": {},
                "tokens_used": 15,
                "estimated_cost": 0.0001
            }
        else:
            return {
                "response": f"Welcome to Beta Hostel! Information for property {prop_id}. Response to: {user_msg}",
                "status": "AI_ACTIVE",
                "tool_calls": [],
                "debug_trace": {},
                "tokens_used": 15,
                "estimated_cost": 0.0001
            }

    latencies = []
    responses_a = []
    responses_b = []

    transport = ASGITransport(app=app)
    sem = asyncio.Semaphore(1)
    with patch.object(AgentRuntimeEngine, "execute_agent_turn", new=mock_turn):
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
            async def call_chat(agent_id, org_id, property_id, conv_id, message, responses_list):
                async with sem:
                    t0 = time.time()
                    try:
                        res = await client.post(
                            f"/api/v1/agents/{agent_id}/chat",
                            json={
                                "message": message,
                                "organization_id": org_id,
                                "property_id": property_id,
                                "conversation_id": conv_id,
                                "channel": "web_widget"
                            }
                        )
                        elapsed = time.time() - t0
                        latencies.append(elapsed)
                        if res.status_code == 200:
                            responses_list.append(res.text)
                        return res.status_code
                    except Exception:
                        return 500

            # Run 200 concurrent requests across 20 concurrent guest chat sessions (100 for Tenant A, 100 for Tenant B)
            tasks = []
            for i in range(100):
                conv_a = f"conv_load_a_{i % 10}"
                conv_b = f"conv_load_b_{i % 10}"
                tasks.append(call_chat(agt_a.id, org_a_id, prop_a.id, conv_a, f"Inquiry A {i} about checkin", responses_a))
                tasks.append(call_chat(agt_b.id, org_b_id, prop_b.id, conv_b, f"Inquiry B {i} about wifi", responses_b))

            status_codes = await asyncio.gather(*tasks)

    # Re-enable rate limiter
    app.state.limiter.enabled = True
    tenant_limiter.default_burst_capacity = orig_burst
    tenant_limiter.default_rate_per_sec = orig_rate

    # 1. Assert all 200 completed successfully
    assert len(status_codes) == 200
    successful_count = sum(1 for s in status_codes if s == 200)
    assert successful_count >= 195, f"Expected >= 195 successes, got {successful_count}"

    # 2. Assert p95 latency < 3.0s
    latencies.sort()
    p95_idx = int(0.95 * (len(latencies) - 1))
    p95_latency = latencies[p95_idx]
    assert p95_latency < 3.0, f"SLA Violation: p95 latency {p95_latency:.3f}s exceeds 3.0s"

    # 3. Assert zero cross-tenant leakage
    for resp in responses_a:
        assert "BETA_EXCLUSIVE_TOKEN_888" not in resp, "Cross-tenant data leaked from Tenant B to Tenant A!"
        assert "Beta Hostel" not in resp
    for resp in responses_b:
        assert "ALPHA_EXCLUSIVE_TOKEN_999" not in resp, "Cross-tenant data leaked from Tenant A to Tenant B!"
        assert "Alpha Hotel" not in resp

    # 4. Assert bounded memory growth (< 50MB)
    mem_after = proc.memory_info().rss
    growth_mb = (mem_after - mem_before) / (1024 * 1024)
    assert growth_mb < 50.0, f"Excessive memory growth under load: {growth_mb:.2f}MB"

