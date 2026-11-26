import pytest
import asyncio
from services.tasks.worker import (
    calculate_backoff_with_jitter,
    compute_task_content_hash,
    execute_task_with_timeout,
    enqueue_task,
    push_to_dlq,
    list_dlq_jobs,
    replay_dlq_job,
    _execute_with_retries,
    DEFAULT_MAX_RETRIES
)
from services.common.redis_service import get_redis_client

def test_p5_exponential_backoff_with_jitter():
    # Verify exponential scaling with full jitter
    b1 = [calculate_backoff_with_jitter(1, base=1.0, max_backoff=60.0) for _ in range(10)]
    b2 = [calculate_backoff_with_jitter(2, base=1.0, max_backoff=60.0) for _ in range(10)]
    b3 = [calculate_backoff_with_jitter(3, base=1.0, max_backoff=60.0) for _ in range(10)]

    assert all(b >= 1.0 for b in b1), "Attempt 1 should be >= base"
    assert sum(b2) / len(b2) > sum(b1) / len(b1), "Attempt 2 average should exceed Attempt 1"
    assert sum(b3) / len(b3) > sum(b2) / len(b2), "Attempt 3 average should exceed Attempt 2"
    assert len(set(b2)) > 1, "Jitter must introduce non-deterministic variance"

    # Max backoff capped
    b_large = calculate_backoff_with_jitter(10, base=1.0, max_backoff=30.0)
    assert b_large <= 30.0, "Backoff must never exceed max_backoff"

def test_p5_content_hash_calculation():
    h1 = compute_task_content_hash("send_notification", {"user_id": "u1", "msg": "hello"})
    h2 = compute_task_content_hash("send_notification", {"msg": "hello", "user_id": "u1"})
    h3 = compute_task_content_hash("send_notification", {"user_id": "u2", "msg": "hello"})

    assert h1 == h2, "Hash must be deterministic regardless of dictionary key order"
    assert h1 != h3, "Distinct payloads must produce distinct hashes"

@pytest.mark.asyncio
async def test_p5_task_deduplication_in_redis():
    payload = {"tenant_id": "org_p5_test", "action": "rollup_metrics"}
    
    # 1. First enqueue
    task_id_1 = await enqueue_task("rollup_usage", payload)
    assert task_id_1 is not None

    # 2. Second enqueue with identical content -> returns deduplicated existing task ID
    task_id_2 = await enqueue_task("rollup_usage", payload)
    assert task_id_1 == task_id_2, "Duplicate task content within 24h must return existing task ID"

@pytest.mark.asyncio
async def test_p5_soft_and_hard_task_timeouts():
    # Fast task finishes within timeout
    async def fast_fn(payload):
        await asyncio.sleep(0.01)
        return "fast_done"

    res = await execute_task_with_timeout(fast_fn, {}, soft_timeout=0.1, hard_timeout=0.5)
    assert res == "fast_done"

    # Slow task exceeding hard timeout is cancelled and raises TimeoutError
    async def slow_fn(payload):
        await asyncio.sleep(0.5)
        return "should_not_reach"

    with pytest.raises(TimeoutError, match="Task exceeded hard timeout"):
        await execute_task_with_timeout(slow_fn, {}, soft_timeout=0.05, hard_timeout=0.1)

@pytest.mark.asyncio
async def test_p5_dlq_push_and_replay():
    envelope = {
        "id": "job_p5_fail_test",
        "task_name": "sync_integration",
        "payload": {"source_id": "src_invalid"},
        "retries_left": 0
    }

    # 1. Push to DLQ
    await push_to_dlq(envelope, "Connection refused: external CRM unreachable")

    # 2. Inspect DLQ
    dlq_jobs = await list_dlq_jobs(limit=10)
    matching = [j for j in dlq_jobs if j.get("id") == "job_p5_fail_test"]
    assert len(matching) > 0, "Job must appear in Dead Letter Queue"
    assert matching[0]["status"] == "DEAD_LETTER"
    assert "Connection refused" in matching[0]["error"]

    # 3. Replay DLQ job
    replay_res = await replay_dlq_job("job_p5_fail_test")
    assert replay_res is not None
    assert replay_res["replayed_job_id"] == "job_p5_fail_test"
    assert "new_task_id" in replay_res
