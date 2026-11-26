import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.config import settings
from services.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError
)
from services.common.redis_service import get_redis_client

@pytest.mark.asyncio
async def test_p10_uniform_error_envelope_404():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/non_existent_endpoint_p10")
        assert res.status_code == 404

        body = res.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] == "NOT_FOUND"
        assert "request_id" in err
        assert res.headers["X-Request-ID"] == err["request_id"]

@pytest.mark.asyncio
async def test_p10_validation_error_envelope_422():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid body for public auth login (missing email and password)
        res = await client.post("/api/v1/auth/login", json={"invalid_field": 123})
        assert res.status_code == 422

        body = res.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] == "VALIDATION_ERROR"
        assert "details" in err
        assert len(err["details"]) > 0
        assert "request_id" in err

@pytest.mark.asyncio
async def test_p10_circuit_breaker_503_envelope():
    from fastapi import APIRouter
    from services.resilience.circuit_breaker import CircuitBreakerOpenError

    test_router = APIRouter()
    @test_router.get("/api/v1/test/cb-open")
    async def throw_cb_open():
        raise CircuitBreakerOpenError(name="sarvam_tts", recovery_time_left=8.5)

    app.include_router(test_router)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/test/cb-open")
        assert res.status_code == 503
        assert "Retry-After" in res.headers
        assert res.headers["Retry-After"] == "8"

        body = res.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] == "CIRCUIT_BREAKER_OPEN"
        assert "sarvam_tts" in err["message"]
        assert err["details"]["circuit"] == "sarvam_tts"

@pytest.mark.asyncio
async def test_p10_zero_stack_trace_leakage_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    from fastapi import APIRouter
    test_router = APIRouter()
    @test_router.get("/api/v1/test/crash")
    async def crash():
        raise ValueError("CRITICAL_INTERNAL_DB_PASSWORD_LEAK: root@10.0.0.5:5432")

    app.include_router(test_router)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/test/crash")
        assert res.status_code == 500

        body = res.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] == "INTERNAL_SERVER_ERROR"
        # Must NOT leak exception text in production
        assert "CRITICAL_INTERNAL_DB_PASSWORD_LEAK" not in str(body)
        assert err["details"] is None
        assert "request_id" in err

@pytest.mark.asyncio
async def test_p10_redis_circuit_breaker_cross_replica_sync():
    cb_name = "test_stripe_gateway_p10"
    cb1 = CircuitBreaker(name=cb_name, failure_threshold=2, recovery_timeout=10.0)

    # 1. Force cb1 into OPEN state
    cb1.state = CircuitState.OPEN
    cb1.consecutive_failures = 2
    await cb1._sync_to_redis()

    # 2. Instance cb2 (simulating replica 2) syncs from Redis
    cb2 = CircuitBreaker(name=cb_name, failure_threshold=2, recovery_timeout=10.0)
    await cb2._sync_from_redis()

    assert cb2.state == CircuitState.OPEN, "Replica 2 must sync OPEN circuit breaker state from Redis"
    assert cb2.consecutive_failures == 2
