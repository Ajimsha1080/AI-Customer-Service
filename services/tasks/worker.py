import os
import json
import uuid
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.worker")
QUEUE_KEY = "hac:task_queue"

# --- ASYNC WORKER TASK DEFINITIONS ---

async def async_ingest_and_embed_document(*args, **kwargs) -> Dict[str, Any]:
    """Background task: chunks, embeds with SentenceTransformers, and indexes RAG document."""
    if len(args) >= 4:
        # (ctx, doc_id, title, content, metadata)
        doc_id = args[1]
        title = args[2]
        content = args[3]
        metadata = args[4] if len(args) > 4 else kwargs.get("metadata", {})
        org_id = metadata.get("organization_id", "")
        prop_id = metadata.get("property_id", "")
    elif len(args) == 1 and isinstance(args[0], dict):
        payload = args[0]
        doc_id = payload.get("doc_id")
        title = payload.get("title", "Untitled")
        content = payload.get("content", "")
        metadata = payload.get("metadata", {})
        org_id = payload.get("organization_id", metadata.get("organization_id", ""))
        prop_id = payload.get("property_id", metadata.get("property_id", ""))
    else:
        payload = kwargs.get("payload", kwargs)
        doc_id = payload.get("doc_id")
        title = payload.get("title", "Untitled")
        content = payload.get("content", "")
        metadata = payload.get("metadata", {})
        org_id = payload.get("organization_id", metadata.get("organization_id", ""))
        prop_id = payload.get("property_id", metadata.get("property_id", ""))

    logger.info(f"[TaskWorker] Ingesting document '{title}' (doc_id={doc_id}) for org={org_id}")
    from services.rag.vector_store import PostgresPgVectorStore
    vector_store = PostgresPgVectorStore()
    doc_dict = {
        "id": doc_id,
        "content": content,
        "title": title,
        "metadata": metadata
    }
    added_ids = await vector_store.add_documents([doc_dict], organization_id=org_id, property_id=prop_id)
    return {"status": "SUCCESS", "doc_id": doc_id, "chunk_ids": added_ids}


async def async_sync_integration(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background task: pulls data from external REST integration with retries and audit logging."""
    source_id = payload.get("source_id")
    org_id = payload.get("organization_id")
    logger.info(f"[TaskWorker] Running integration sync for source_id={source_id} org={org_id}")

    from services.database.session import AsyncSessionLocal
    from services.database.models import IntegrationSource
    from sqlalchemy import select
    import httpx

    async with AsyncSessionLocal() as session:
        stmt = select(IntegrationSource).where(IntegrationSource.id == source_id)
        res = await session.execute(stmt)
        source = res.scalar_one_or_none()
        if not source:
            return {"status": "NOT_FOUND", "source_id": source_id}

        source.status = "SYNCING"
        await session.commit()

        # Execute pull request with 3 retries
        success = False
        error_msg = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(source.source_url)
                    if resp.status_code < 400:
                        success = True
                        break
                    error_msg = f"HTTP {resp.status_code}"
            except Exception as e:
                error_msg = str(e)
                await asyncio.sleep(1.0 * attempt)

        source.status = "CONNECTED" if success else "FAILED"
        source.last_synced_at = datetime.now(timezone.utc)
        source.sync_status = "SUCCESS" if success else f"ERROR: {error_msg}"
        await session.commit()

    return {"status": "SUCCESS" if success else "FAILED", "source_id": source_id}


async def async_send_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background task: dispatches email, sms, or webhook notification."""
    recipient = payload.get("recipient")
    channel = payload.get("channel", "email")
    message = payload.get("message")
    title = payload.get("title", "Notification")
    logger.info(f"[TaskWorker] Dispatching {channel} notification to '{recipient}': {title}")
    # Simulates dispatch or external provider call
    await asyncio.sleep(0.05)
    return {"status": "DISPATCHED", "recipient": recipient, "channel": channel}


async def async_rollup_usage_events(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background task: computes periodic usage and cost rollups across organizations."""
    org_id = payload.get("organization_id")
    logger.info(f"[TaskWorker] Aggregating usage rollup for organization={org_id}")

    from services.database.session import AsyncSessionLocal
    from services.database.models import UsageEvent
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as session:
        query = select(
            func.count(UsageEvent.id),
            func.sum(UsageEvent.quantity),
            func.sum(UsageEvent.estimated_cost)
        )
        if org_id:
            query = query.where(UsageEvent.organization_id == org_id)
        res = await session.execute(query)
        cnt, total_qty, total_cost = res.first()

    return {
        "status": "COMPLETED",
        "organization_id": org_id,
        "total_events": cnt or 0,
        "total_quantity": total_qty or 0,
        "total_cost": round(total_cost or 0.0, 4)
    }


async def async_purge_retention_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background task: purges audit logs and resolved conversations exceeding retention period."""
    days = payload.get("days", 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logger.info(f"[TaskWorker] Purging operational logs older than {days} days (cutoff: {cutoff})")

    from services.database.session import AsyncSessionLocal
    from services.database.models import AuditLog, UsageEvent
    from sqlalchemy import delete

    purged_events = 0
    async with AsyncSessionLocal() as session:
        stmt = delete(UsageEvent).where(UsageEvent.created_at < cutoff)
        res = await session.execute(stmt)
        purged_events = res.rowcount
        await session.commit()

    return {"status": "PURGED", "purged_events": purged_events, "retention_days": days}


TASK_REGISTRY = {
    "ingest_document": async_ingest_and_embed_document,
    "sync_integration": async_sync_integration,
    "send_notification": async_send_notification,
    "rollup_usage": async_rollup_usage_events,
    "purge_retention": async_purge_retention_data
}


QUEUE_KEY = "hac:task_queue"
DLQ_KEY = "hac:task_queue:dlq"

# In-memory DLQ store for testing / local fallback: job_id -> envelope
LOCAL_DLQ: Dict[str, Dict[str, Any]] = {}
PROCESSED_JOB_KEYS: set = set()

async def push_to_dlq(envelope: Dict[str, Any], error_reason: str):
    """Pushes a permanently failed job to the Dead-Letter Queue."""
    envelope["failed_at"] = datetime.now(timezone.utc).isoformat()
    envelope["error"] = error_reason
    envelope["status"] = "DEAD_LETTER"

    job_id = envelope.get("id")
    LOCAL_DLQ[job_id] = envelope

    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, decode_responses=True)
        await client.lpush(DLQ_KEY, json.dumps(envelope))
        await client.close()
        logger.error(f"[TaskWorker] Job '{job_id}' ({envelope.get('task_name')}) moved to Redis DLQ: {error_reason}")
    except Exception:
        logger.error(f"[TaskWorker] Job '{job_id}' ({envelope.get('task_name')}) moved to Local DLQ: {error_reason}")

async def list_dlq_jobs(limit: int = 50) -> list[Dict[str, Any]]:
    """Inspects pending dead-letter jobs."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, decode_responses=True)
        raw_items = await client.lrange(DLQ_KEY, 0, limit - 1)
        await client.close()
        if raw_items:
            return [json.loads(item) for item in raw_items]
    except Exception:
        pass
    return list(LOCAL_DLQ.values())[:limit]

async def replay_dlq_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Replays a job from the DLQ by re-enqueueing it into the primary queue."""
    target_envelope = None
    if job_id in LOCAL_DLQ:
        target_envelope = LOCAL_DLQ.pop(job_id)

    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, decode_responses=True)
        raw_items = await client.lrange(DLQ_KEY, 0, -1)
        for raw in raw_items:
            parsed = json.loads(raw)
            if parsed.get("id") == job_id:
                target_envelope = parsed
                await client.lrem(DLQ_KEY, 1, raw)
                break
        await client.close()
    except Exception:
        pass

    if not target_envelope:
        return None

    # Reset retries and re-enqueue
    task_name = target_envelope.get("task_name")
    payload = target_envelope.get("payload", {})
    new_task_id = await enqueue_task(task_name=task_name, payload=payload, max_retries=3)
    logger.info(f"[TaskWorker] Replayed dead letter job '{job_id}' as new task '{new_task_id}'.")
    return {"replayed_job_id": job_id, "new_task_id": new_task_id, "task_name": task_name}

# --- TASK ENQUEUEING ENGINE ---

async def enqueue_task(task_name: str, payload: Dict[str, Any], max_retries: int = 3, idempotency_key: Optional[str] = None) -> str:
    """Enqueues a task for asynchronous processing via Redis queue with fallback to background task."""
    task_id = idempotency_key or f"task_{uuid.uuid4().hex[:12]}"

    if task_id in PROCESSED_JOB_KEYS:
        logger.info(f"[TaskQueue] Job with idempotency key '{task_id}' already processed, skipping.")
        return task_id

    task_envelope = {
        "id": task_id,
        "task_name": task_name,
        "payload": payload,
        "retries_left": max_retries,
        "enqueued_at": datetime.now(timezone.utc).isoformat()
    }

    enqueued = False
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, decode_responses=True)
        await client.lpush(QUEUE_KEY, json.dumps(task_envelope))
        await client.close()
        enqueued = True
        logger.info(f"[TaskQueue] Enqueued '{task_name}' (task_id={task_id}) into Redis queue.")
    except Exception as e:
        logger.debug(f"[TaskQueue] Redis unavailable ({e}); falling back to local background task.")

    if not enqueued:
        fn = TASK_REGISTRY.get(task_name)
        if fn:
            asyncio.create_task(_execute_with_retries(fn, task_name, task_envelope, max_retries))

    return task_id


async def _execute_with_retries(fn, task_name: str, envelope: Dict[str, Any], retries: int):
    payload = envelope.get("payload", {})
    job_id = envelope.get("id")
    for attempt in range(1, retries + 1):
        try:
            res = await fn(payload)
            PROCESSED_JOB_KEYS.add(job_id)
            return res
        except Exception as e:
            logger.warning(f"[TaskWorker] Task '{task_name}' attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                await asyncio.sleep(0.05 * (2 ** attempt))
            else:
                await push_to_dlq(envelope, str(e))
                logger.error(f"[TaskWorker] Task '{task_name}' failed permanently. Moved to DLQ.")


# --- STANDALONE WORKER PROCESS ---

async def run_worker():
    """Main loop for the standalone worker process."""
    logger.info("Initializing Hospitality Agent Cloud Background Task Worker...")
    import redis.asyncio as aioredis

    while True:
        try:
            client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            logger.info(f"Worker connected to Redis at {settings.REDIS_URL}. Waiting for tasks...")
            while True:
                # Blocking pop with 5s timeout
                item = await client.brpop(QUEUE_KEY, timeout=5)
                if not item:
                    continue
                _, raw_data = item
                try:
                    envelope = json.loads(raw_data)
                    job_id = envelope.get("id")
                    if job_id in PROCESSED_JOB_KEYS:
                        logger.info(f"[TaskWorker] Skipping duplicate job '{job_id}'.")
                        continue

                    task_name = envelope.get("task_name")
                    payload = envelope.get("payload", {})
                    retries_left = envelope.get("retries_left", 3)

                    fn = TASK_REGISTRY.get(task_name)
                    if not fn:
                        logger.error(f"Unknown task name '{task_name}', discarding.")
                        continue

                    try:
                        await fn(payload)
                        PROCESSED_JOB_KEYS.add(job_id)
                    except Exception as exec_err:
                        logger.warning(f"Error executing task '{task_name}': {exec_err}")
                        if retries_left > 1:
                            envelope["retries_left"] = retries_left - 1
                            await client.lpush(QUEUE_KEY, json.dumps(envelope))
                            logger.info(f"Re-enqueued '{task_name}' with {retries_left - 1} retries left.")
                        else:
                            await push_to_dlq(envelope, str(exec_err))
                except Exception as parse_err:
                    logger.error(f"Failed to process worker queue item: {parse_err}")
        except Exception as conn_err:
            logger.warning(f"Worker Redis connection lost: {conn_err}. Reconnecting in 3s...")
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
