import logging
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Optional
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.redis")

_redis_client = None
_redis_client_sync = None
_fake_server = None

def _get_fake_server():
    global _fake_server
    if _fake_server is None:
        import fakeredis
        _fake_server = fakeredis.FakeServer()
    return _fake_server

def get_redis_connection_params():
    """Builds normalized connection parameters for Redis with TLS, Auth, and Sentinel/Cluster support."""
    url = settings.REDIS_URL
    if settings.REDIS_TLS and url.startswith("redis://"):
        url = url.replace("redis://", "rediss://", 1)

    kwargs = {
        "decode_responses": True,
        "max_connections": settings.REDIS_MAX_CONNECTIONS,
    }
    if settings.REDIS_PASSWORD:
        kwargs["password"] = settings.REDIS_PASSWORD

    if settings.is_production:
        has_auth = bool(settings.REDIS_PASSWORD) or ("@" in url and not url.startswith("redis://@") and not url.startswith("rediss://@"))
        if not has_auth:
            raise RuntimeError("CRITICAL: Redis authentication (REDIS_PASSWORD) is required in production.")

    return url, kwargs

async def get_redis_client():
    """
    Centralized Redis connection provider:
    - Production: Strictly connects to real Redis instance with TLS and authentication. Fails at startup if unreachable.
    - Development / Testing: Connects to real Redis if reachable; falls back to fakeredis for zero-mock in-memory tests.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    import redis.asyncio as aioredis
    url, kwargs = get_redis_connection_params()

    if settings.is_production:
        try:
            if settings.REDIS_SENTINEL_HOSTS:
                from redis.asyncio.sentinel import Sentinel
                hosts = [
                    (h.split(":")[0], int(h.split(":")[1]))
                    for h in settings.REDIS_SENTINEL_HOSTS.split(",")
                    if ":" in h
                ]
                sentinel = Sentinel(hosts, socket_timeout=1.0, **kwargs)
                client = sentinel.master_for(settings.REDIS_SENTINEL_MASTER)
            elif settings.REDIS_CLUSTER_MODE:
                from redis.asyncio.cluster import RedisCluster
                client = RedisCluster.from_url(url, socket_connect_timeout=1.0, **kwargs)
            else:
                client = aioredis.from_url(url, socket_connect_timeout=1.0, **kwargs)

            await client.ping()
            _redis_client = client
            return _redis_client
        except Exception as e:
            logger.critical(f"FATAL: Redis is unreachable in production environment: {e}")
            raise RuntimeError(f"CRITICAL: Production requires active Redis instance ({url}): {e}")
    else:
        try:
            client = aioredis.from_url(url, socket_connect_timeout=0.3, **kwargs)
            await client.ping()
            _redis_client = client
            return _redis_client
        except Exception:
            import fakeredis.aioredis
            _redis_client = fakeredis.aioredis.FakeRedis(server=_get_fake_server(), decode_responses=True)
            return _redis_client

def get_redis_client_sync():
    """Sync accessor returning either connected client or sync FakeRedis sharing same fake server."""
    global _redis_client_sync
    if _redis_client_sync is not None:
        return _redis_client_sync

    import redis
    url, kwargs = get_redis_connection_params()
    if settings.is_production:
        try:
            client = redis.from_url(url, socket_connect_timeout=1.0, **kwargs)
            client.ping()
            _redis_client_sync = client
            return _redis_client_sync
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Production requires active Redis instance ({url}): {e}")
    else:
        try:
            client = redis.from_url(url, socket_connect_timeout=0.3, **kwargs)
            client.ping()
            _redis_client_sync = client
            return _redis_client_sync
        except Exception:
            import fakeredis
            _redis_client_sync = fakeredis.FakeRedis(server=_get_fake_server(), decode_responses=True)
            return _redis_client_sync

@asynccontextmanager
async def acquire_distributed_lock(lock_key: str, ttl_seconds: int = 10, acquire_timeout: float = 2.0):
    """
    Redis-backed distributed lock with TTL to prevent concurrent double-booking
    or race conditions across distributed API replicas.
    """
    client = await get_redis_client()
    lock_val = str(uuid.uuid4())
    start_time = asyncio.get_running_loop().time()
    acquired = False
    try:
        while asyncio.get_running_loop().time() - start_time < acquire_timeout:
            res = await client.set(lock_key, lock_val, ex=ttl_seconds, nx=True)
            if res:
                acquired = True
                break
            await asyncio.sleep(0.05)
        if not acquired:
            raise RuntimeError(f"LockAcquisitionTimeout: Failed to acquire lock {lock_key} within {acquire_timeout}s")
        yield lock_val
    finally:
        if acquired:
            try:
                val = await client.get(lock_key)
                if val == lock_val:
                    await client.delete(lock_key)
            except Exception:
                pass

