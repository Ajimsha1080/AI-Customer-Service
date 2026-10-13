import pytest
import asyncio
import time
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.auth import create_access_token
from services.resilience.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitBreakerOpenError, get_circuit_breaker
)
from services.resilience.tenant_limiter import TenantTokenBucketLimiter
from services.ai.resilience_router import LLMResilienceRouter
from services.tasks.worker import (
    enqueue_task, list_dlq_jobs, replay_dlq_job, LOCAL_DLQ, PROCESSED_JOB_KEYS
)
from apps.api.middleware.idempotency import verify_etag_concurrency
from services.database.pagination import encode_cursor, decode_cursor, build_cursor_page_response

client = TestClient(app)

@pytest.mark.asyncio
async def test_circuit_breaker_tripping_and_half_open_recovery():
    """F3.1 Outbound circuit breaker: trips to OPEN after threshold failures, blocks calls, and recovers in HALF_OPEN."""
    cb = CircuitBreaker(
        name="test_erp_service",
        failure_threshold=3,
        recovery_timeout=0.2,
        call_timeout=1.0
    )
    assert cb.state == CircuitState.CLOSED

    # Failing function
    async def failing_call():
        raise ConnectionResetError("ERP connection reset by peer")

    # Succeeding function
    async def passing_call():
        return {"status": "ok"}

    # 1. First 2 failures: still CLOSED
    for _ in range(2):
        with pytest.raises(ConnectionResetError):
            await cb.call(failing_call)
        assert cb.state == CircuitState.CLOSED

    # 2. 3rd failure: Trips breaker to OPEN
    with pytest.raises(ConnectionResetError):
        await cb.call(failing_call)
    assert cb.state == CircuitState.OPEN
    assert cb.consecutive_failures == 3

    # 3. Next call immediately blocked by CircuitBreakerOpenError without invoking target
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await cb.call(passing_call)
    assert "is OPEN" in str(exc_info.value)

    # 4. Wait for recovery timeout -> transitions to HALF_OPEN probe
    await asyncio.sleep(0.25)

    # First probe success
    res1 = await cb.call(passing_call)
    assert res1["status"] == "ok"
    assert cb.state == CircuitState.HALF_OPEN

    # Second probe success -> recovers to CLOSED
    res2 = await cb.call(passing_call)
    assert res2["status"] == "ok"
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0


@pytest.mark.asyncio
async def test_tenant_rate_limiter_noisy_neighbor_isolation():
    """F3.2 Per-tenant token bucket rate limits: noisy-neighbor protection, 429 calculation, and isolation."""
    limiter = TenantTokenBucketLimiter(default_rate_per_sec=0.1, default_burst_capacity=3)
    org_noisy = f"org_noisy_{uuid.uuid4().hex[:6]}"
    org_quiet = f"org_quiet_{uuid.uuid4().hex[:6]}"

    # Tenant 1 consumes entire burst capacity (3 tokens)
    ok1, rem1, _ = await limiter.consume(org_noisy, cost=1)
    assert ok1 is True
    assert rem1 == 2

    ok2, rem2, _ = await limiter.consume(org_noisy, cost=1)
    assert ok2 is True
    assert rem2 == 1

    ok3, rem3, _ = await limiter.consume(org_noisy, cost=1)
    assert ok3 is True
    assert rem3 == 0

    # Tenant 1 attempts 4th request -> Denied with Retry-After
    ok4, rem4, retry_after = await limiter.consume(org_noisy, cost=1)
    assert ok4 is False
    assert rem4 == 0
    assert retry_after >= 0.1

    # Quiet neighbor Tenant 2 is completely unaffected (isolated bucket)
    ok_quiet, rem_quiet, _ = await limiter.consume(org_quiet, cost=1)
    assert ok_quiet is True
    assert rem_quiet == 2


@pytest.mark.asyncio
async def test_llm_resilience_failover_spend_caps_and_degraded_mode():
    """F3.3 LLM provider failover (primary -> secondary), per-tenant spend caps, prompt caching, and degraded mode."""
    router = LLMResilienceRouter()
    org_id = f"org_ai_{uuid.uuid4().hex[:6]}"

    async def mock_primary_down():
        raise TimeoutError("OpenAI API 504 Gateway Timeout")

    async def mock_secondary_success():
        return "Anthropic Claude Concierge: The swimming pool is open until 10 PM."

    # 1. Primary provider fails -> Seamless failover to secondary provider
    resp = await router.generate_response(
        org_id=org_id,
        prompt="When does the pool close?",
        primary_callable=mock_primary_down,
        secondary_callable=mock_secondary_success,
        estimated_cost_usd=0.01
    )
    assert resp["provider"] == "secondary"
    assert "swimming pool is open until 10 PM" in resp["content"]
    assert resp["is_degraded"] is False

    # 2. Prompt Cache HIT on identical prompt
    resp_cache = await router.generate_response(
        org_id=org_id,
        prompt="When does the pool close?",
        primary_callable=mock_primary_down,
        secondary_callable=mock_secondary_success
    )
    assert resp_cache["provider"] == "cache"
    assert resp_cache["is_cached"] is True
    assert "swimming pool is open until 10 PM" in resp_cache["content"]

    # 3. Spend Cap Enforcement: Set low spend cap and exceed it
    router.set_spend_cap(org_id, cap_usd=0.01) # Spend is already 0.01

    resp_degraded = await router.generate_response(
        org_id=org_id,
        prompt="Can I book the penthouse suite?",
        primary_callable=mock_secondary_success,
        estimated_cost_usd=0.005
    )
    assert resp_degraded["is_degraded"] is True
    assert resp_degraded["degraded_reason"] == "TENANT_SPEND_CAP_EXCEEDED"
    # Invariant: Never invents room availability or booking in degraded mode
    assert "maintenance mode" in resp_degraded["content"]


@pytest.mark.asyncio
async def test_worker_dead_letter_queue_and_replay():
    """F3.4 Background worker retries, dead-letter queue (DLQ) capture, and manual replay."""
    LOCAL_DLQ.clear()
    PROCESSED_JOB_KEYS.clear()

    # Enqueue a failing task (e.g. unknown task or failing payload)
    failing_task_id = f"failing_task_{uuid.uuid4().hex[:6]}"

    envelope = {
        "id": failing_task_id,
        "task_name": "sync_integration",
        "payload": {"source_id": "non_existent_source_id"},
        "retries_left": 1
    }

    from services.tasks.worker import push_to_dlq
    await push_to_dlq(envelope, error_reason="HTTP 502 Bad Gateway from PMS Integration")

    # Inspect DLQ
    dlq_jobs = await list_dlq_jobs()
    matched = [j for j in dlq_jobs if j.get("id") == failing_task_id]
    assert len(matched) == 1
    assert matched[0]["status"] == "DEAD_LETTER"
    assert "HTTP 502" in matched[0]["error"]

    # Replay DLQ job
    replay_res = await replay_dlq_job(failing_task_id)
    assert replay_res is not None
    assert replay_res["replayed_job_id"] == failing_task_id
    assert "new_task_id" in replay_res

    # Job is removed from DLQ after replay
    dlq_after = await list_dlq_jobs()
    assert not any(j.get("id") == failing_task_id for j in dlq_after)


def test_api_idempotency_key_middleware_and_replay():
    """F3.5 Idempotency-Key middleware: executes once, caches response, and replays on duplicate."""
    idem_key = f"idem_{uuid.uuid4().hex}"
    headers = {
        "Idempotency-Key": idem_key,
        "X-Tenant-ID": "test_org"
    }

    # First request: Executes /api/v1/auth/forgot-password
    r1 = client.post("/api/v1/auth/forgot-password", headers=headers, json={
        "email": "idempotent_user@enterprise.test"
    })
    assert r1.status_code == 200
    assert r1.headers.get("Idempotency-Replayed") is None

    # Duplicate request with same Idempotency-Key: Returns cached response
    r2 = client.post("/api/v1/auth/forgot-password", headers=headers, json={
        "email": "idempotent_user@enterprise.test"
    })
    assert r2.status_code == 200
    assert r2.headers.get("X-Cache-Lookup") == "HIT"
    assert r2.headers.get("Idempotency-Replayed") == "true"
    assert r2.json() == r1.json()


def test_optimistic_concurrency_and_cursor_pagination():
    """F3.6 Optimistic concurrency (ETag / If-Match) and cursor-based pagination."""
    # 1. Optimistic concurrency
    current_version = 4
    assert verify_etag_concurrency(current_version, 'W/"4"') is True
    assert verify_etag_concurrency(current_version, '"4"') is True
    assert verify_etag_concurrency(current_version, '"3"') is False

    # 2. Cursor pagination
    now = datetime.now(timezone.utc)
    item_id = "resv_12345"
    encoded = encode_cursor(now, item_id)
    assert isinstance(encoded, str)

    dec_time, dec_id = decode_cursor(encoded)
    assert dec_id == item_id
    assert dec_time is not None

    # Cursor page response builder
    mock_items = [
        {"id": f"item_{i}", "created_at": now}
        for i in range(5)
    ]
    page = build_cursor_page_response(
        items=mock_items,
        limit=3,
        get_created_at_and_id_fn=lambda x: (x["created_at"], x["id"])
    )
    assert len(page["items"]) == 3
    assert page["has_more"] is True
    assert page["next_cursor"] is not None
