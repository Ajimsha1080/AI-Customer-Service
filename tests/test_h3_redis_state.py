import pytest
import uuid
import json
from unittest.mock import patch
from apps.api.auth import (
    record_failed_login,
    check_login_lockout,
    reset_login_failures,
    revoke_refresh_token,
    decode_refresh_token_async,
    create_refresh_token
)
from services.operations.feature_flags import feature_flags
from services.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenError
from services.security.encryption import EnvelopeEncryptionService
from services.security.email_service import email_service
from services.tasks.worker import push_to_dlq, list_dlq_jobs, DLQ_KEY
from services.common.redis_service import get_redis_client, get_redis_client_sync

@pytest.mark.asyncio
async def test_h3_account_and_ip_lockout():
    """H3: Lockout keys on account+IP with backoff."""
    from fastapi import HTTPException
    email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    ip1 = "198.51.100.10"
    ip2 = "198.51.100.20"

    # Initially not locked out (should not raise)
    await check_login_lockout(email, ip1)
    await check_login_lockout(email, ip2)

    # Record 5 failures from ip1
    for _ in range(5):
        await record_failed_login(email, ip1)

    # Now ip1 should be locked out (raises 429)
    with pytest.raises(HTTPException) as exc:
        await check_login_lockout(email, ip1)
    assert exc.value.status_code == 429

    # ip2 should NOT be locked out for the same email
    await check_login_lockout(email, ip2)

    # Reset clears lockout for ip1
    await reset_login_failures(email, ip1)
    await check_login_lockout(email, ip1)

@pytest.mark.asyncio
async def test_h3_refresh_token_denylist_in_redis():
    """H3: REFRESH_TOKEN_DENYLIST is backed by Redis."""
    user_id = str(uuid.uuid4())
    token = create_refresh_token({"sub": user_id, "org_id": "org_test"})

    # Valid token can be decoded
    payload = await decode_refresh_token_async(token)
    assert payload["sub"] == user_id

    # Revoke it
    await revoke_refresh_token(token)

    # Now decoding must be rejected
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await decode_refresh_token_async(token)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()

@pytest.mark.asyncio
async def test_h3_circuit_breaker_distributed_state():
    """H3: Circuit breaker state is tracked in Redis."""
    cb_name = f"cb_test_{uuid.uuid4().hex[:6]}"
    cb = CircuitBreaker(name=cb_name, failure_threshold=2, recovery_timeout=5.0)

    async def failing_call():
        raise ValueError("Service down")

    # Trip breaker by exceeding failure threshold
    with pytest.raises(ValueError):
        await cb.call(failing_call)
    with pytest.raises(ValueError):
        await cb.call(failing_call)

    # Next call should be blocked immediately with CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(failing_call)

    # Check state persisted in Redis
    r = await get_redis_client()
    state = await r.get(f"hac:cb:{cb_name}:state")
    assert state == "OPEN"

def test_h3_feature_flags_and_kill_switches_in_redis():
    """H3: Feature flags and kill switches persist across replicas via Redis."""
    flag_name = f"flag_{uuid.uuid4().hex[:6]}"
    feature_flags.set_flag(flag_name, enabled=True, rollout_pct=100)
    assert feature_flags.is_enabled(flag_name) is True

    # Kill switch engagement
    ks_name = f"kill_switch_{uuid.uuid4().hex[:6]}"
    assert feature_flags.is_kill_switch_active(ks_name) is False
    feature_flags.activate_kill_switch(ks_name)
    assert feature_flags.is_kill_switch_active(ks_name) is True

    # Deactivation
    feature_flags.deactivate_kill_switch(ks_name)
    assert feature_flags.is_kill_switch_active(ks_name) is False

def test_h3_byok_encryption_keys_in_redis():
    """H3: BYOK keys stored in Redis."""
    service = EnvelopeEncryptionService()
    org_id = f"org_{uuid.uuid4().hex[:6]}"
    byok_key_hex = "a" * 64

    service.register_tenant_byok(org_id, byok_key_hex)
    kek = service._get_kek(org_id)
    assert kek == bytes.fromhex(byok_key_hex)

    # Check key exists in Redis
    r = get_redis_client_sync()
    stored = r.get(f"hac:byok:{org_id}")
    assert stored is not None

    service.remove_tenant_byok(org_id)
    assert service._get_kek(org_id) == service.root_kek

@pytest.mark.asyncio
async def test_h3_dlq_in_redis():
    """H3: DLQ writes and reads from Redis."""
    envelope = {
        "id": f"job_{uuid.uuid4().hex[:8]}",
        "task_name": "test_task",
        "payload": {"data": 123}
    }
    await push_to_dlq(envelope, "Network timeout")

    jobs = await list_dlq_jobs(limit=10)
    job_ids = [j.get("id") for j in jobs]
    assert envelope["id"] in job_ids

def test_h3_email_suppression_list_in_redis():
    """H3: Email suppression list in Redis."""
    email = f"bounced_{uuid.uuid4().hex[:6]}@example.com"
    assert email_service.is_suppressed(email) is False

    email_service.record_bounce(email)
    assert email_service.is_suppressed(email) is True
