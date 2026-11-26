import asyncio
import logging
from services.tasks.worker import (
    run_worker,
    enqueue_task,
    push_to_dlq,
    list_dlq_jobs,
    replay_dlq_job,
    calculate_backoff_with_jitter,
    compute_task_content_hash,
    execute_task_with_timeout,
    TASK_REGISTRY,
    QUEUE_KEY,
    DLQ_KEY,
    DEFAULT_MAX_RETRIES,
    SOFT_TASK_TIMEOUT_SECONDS,
    HARD_TASK_TIMEOUT_SECONDS
)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
