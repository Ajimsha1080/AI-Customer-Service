import time
import math
import logging
from typing import Tuple, Dict, Any, Optional
from fastapi import Request, HTTPException, status
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.resilience.tenant_limiter")

LUA_TOKEN_BUCKET = """
local key_tokens = KEYS[1]
local key_last = KEYS[2]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local last_tokens = tonumber(redis.call('get', key_tokens))
local last_time = tonumber(redis.call('get', key_last))

if not last_tokens then
    last_tokens = capacity
    last_time = now
end

local delta = math.max(0, now - last_time)
local tokens = math.min(capacity, last_tokens + (delta * rate))

if tokens >= cost then
    tokens = tokens - cost
    redis.call('set', key_tokens, tokens, 'EX', 3600)
    redis.call('set', key_last, now, 'EX', 3600)
    return {1, math.floor(tokens), 0}
else
    local needed = cost - tokens
    local retry_after = math.ceil(needed / rate)
    return {0, 0, retry_after}
end
"""

class TenantTokenBucketLimiter:
    """
    Per-tenant token bucket rate limiter providing noisy-neighbor protection
    separate from billing quotas.
    Returns: (is_allowed, remaining_tokens, retry_after_seconds)
    """
    def __init__(self, default_rate_per_sec: float = 20.0, default_burst_capacity: int = 40):
        self.default_rate_per_sec = default_rate_per_sec
        self.default_burst_capacity = default_burst_capacity
        self._local_buckets: Dict[str, Dict[str, float]] = {}
        self._redis_client = None

    def _get_redis(self):
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3, decode_responses=True)
            except Exception:
                self._redis_client = None
        return self._redis_client

    async def consume(
        self,
        org_id: str,
        cost: int = 1,
        rate_per_sec: Optional[float] = None,
        burst_capacity: Optional[int] = None
    ) -> Tuple[bool, int, float]:
        rate = rate_per_sec if rate_per_sec is not None else self.default_rate_per_sec
        capacity = burst_capacity if burst_capacity is not None else self.default_burst_capacity
        now = time.time()

        r_client = self._get_redis()
        if r_client:
            try:
                key_tokens = f"hac:ratelimit:tb:{org_id}:tokens"
                key_last = f"hac:ratelimit:tb:{org_id}:last"
                res = await r_client.eval(
                    LUA_TOKEN_BUCKET,
                    2,
                    key_tokens,
                    key_last,
                    capacity,
                    rate,
                    cost,
                    now
                )
                is_ok = bool(res[0] == 1)
                remaining = int(res[1])
                retry_after = float(res[2])
                return is_ok, remaining, retry_after
            except Exception:
                # If Redis times out or fails, fallback to local in-memory
                pass

        return self._consume_local(org_id, cost, rate, capacity, now)

    def _consume_local(
        self,
        org_id: str,
        cost: int,
        rate: float,
        capacity: int,
        now: float
    ) -> Tuple[bool, int, float]:
        if org_id not in self._local_buckets:
            self._local_buckets[org_id] = {
                "tokens": float(capacity),
                "last_updated": now
            }

        bucket = self._local_buckets[org_id]
        delta = max(0.0, now - bucket["last_updated"])
        bucket["tokens"] = min(float(capacity), bucket["tokens"] + (delta * rate))
        bucket["last_updated"] = now

        if bucket["tokens"] >= cost:
            bucket["tokens"] -= cost
            return True, int(bucket["tokens"]), 0.0
        else:
            needed = cost - bucket["tokens"]
            retry_after = math.ceil(needed / rate) if rate > 0 else 60.0
            return False, 0, float(max(1.0, retry_after))

    def reset_org(self, org_id: str):
        if org_id in self._local_buckets:
            del self._local_buckets[org_id]

    async def reset_org_async(self, org_id: str):
        self.reset_org(org_id)
        r = self._get_redis()
        if r:
            try:
                await r.delete(f"hac:ratelimit:tb:{org_id}:tokens", f"hac:ratelimit:tb:{org_id}:last")
            except Exception:
                pass

tenant_limiter = TenantTokenBucketLimiter()

async def enforce_tenant_fair_use_quota(request: Request, cost: int = 1):
    """
    FastAPI dependency that enforces per-tenant noisy-neighbor rate limits.
    Injects 429 Too Many Requests with Retry-After header when rate exceeded.
    """
    org_id = (
        getattr(request.state, "tenant_id", None)
        or getattr(request.state, "organization_id", None)
        or request.headers.get("X-Tenant-ID")
        or request.headers.get("x-tenant-id")
        or "global_anonymous"
    )
    allowed, remaining, retry_after = await tenant_limiter.consume(org_id=org_id, cost=cost)

    if not allowed:
        logger.warning(f"[RateLimit] Tenant '{org_id}' exceeded fair-use quota. Retry-After: {retry_after}s")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"FAIR_USE_QUOTA_EXCEEDED: Tenant '{org_id}' rate limit reached. Please back off.",
            headers={
                "Retry-After": str(int(retry_after)),
                "X-RateLimit-Limit": str(tenant_limiter.default_burst_capacity),
                "X-RateLimit-Remaining": "0"
            }
        )
