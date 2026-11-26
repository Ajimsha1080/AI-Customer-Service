import logging
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

async def get_redis_client():
    """
    Centralized Redis connection provider:
    - Production: Strictly connects to real Redis instance. Fails at startup if unreachable.
    - Development / Testing: Connects to real Redis if reachable; falls back to fakeredis for zero-mock in-memory tests.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    import redis.asyncio as aioredis
    if settings.is_production:
        try:
            client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1.0, decode_responses=True)
            await client.ping()
            _redis_client = client
            return _redis_client
        except Exception as e:
            logger.critical(f"FATAL: Redis is unreachable in production environment: {e}")
            raise RuntimeError(f"CRITICAL: Production requires active Redis instance ({settings.REDIS_URL}): {e}")
    else:
        try:
            client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3, decode_responses=True)
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
    if settings.is_production:
        try:
            client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1.0, decode_responses=True)
            client.ping()
            _redis_client_sync = client
            return _redis_client_sync
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Production requires active Redis instance ({settings.REDIS_URL}): {e}")
    else:
        try:
            client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3, decode_responses=True)
            client.ping()
            _redis_client_sync = client
            return _redis_client_sync
        except Exception:
            import fakeredis
            _redis_client_sync = fakeredis.FakeRedis(server=_get_fake_server(), decode_responses=True)
            return _redis_client_sync
