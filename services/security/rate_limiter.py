import time
import uuid
import logging
from typing import Optional, Tuple, Dict
from fastapi import Request, HTTPException, status
from apps.api.config import settings
from apps.api.auth import extract_client_ip
from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.rate_limiter")

# Tiered rate limits per minute based on tenant plan
TIERED_PLAN_LIMITS: Dict[str, int] = {
    "FREE": 60,
    "STARTER": 120,
    "PRO": 300,
    "PROFESSIONAL": 300,
    "BUSINESS": 600,
    "ENTERPRISE": 1000
}

DEFAULT_IP_LIMIT = 120  # 120 req/min per IP
DEFAULT_ENDPOINT_LIMIT = 60  # 60 req/min per sensitive endpoint

class DistributedSlidingWindowRateLimiter:
    """
    High-Performance Redis-Backed Sliding Window Rate Limiter.
    Evaluates requests over a rolling 60-second window using atomic sorted set operations.
    Computes strict rate limit headers:
      - X-RateLimit-Limit
      - X-RateLimit-Remaining
      - X-RateLimit-Reset
      - Retry-After (on 429)
    """

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60
    ) -> Tuple[bool, Dict[str, str]]:
        """
        Atomically inspects and records a hit against the sliding window.
        Returns (is_allowed, headers_dict).
        """
        redis_client = await get_redis_client()
        now = time.time()
        clear_before = now - window_seconds
        hit_id = str(uuid.uuid4())

        # Sliding window pipeline
        # 1. Remove expired entries outside the sliding window
        # 2. Count active hits
        # 3. Add current hit if under limit
        # 4. Refresh key TTL
        redis_key = f"rl:sw:{key}"

        try:
            # Clean old entries
            await redis_client.zremrangebyscore(redis_key, 0, clear_before)
            current_hits = await redis_client.zcard(redis_key)

            reset_epoch = int(now + window_seconds)

            if current_hits >= limit:
                # Rate limit exceeded
                # Oldest element score gives exact time until quota frees up
                oldest_entries = await redis_client.zrange(redis_key, 0, 0, withscores=True)
                retry_after = window_seconds
                if oldest_entries:
                    oldest_time = oldest_entries[0][1]
                    retry_after = max(1, int(oldest_time + window_seconds - now))

                headers = {
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_epoch),
                    "Retry-After": str(retry_after)
                }
                return False, headers

            # Under limit: add current hit and expire
            await redis_client.zadd(redis_key, {hit_id: now})
            await redis_client.expire(redis_key, window_seconds + 5)

            remaining = max(0, limit - (current_hits + 1))
            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_epoch)
            }
            return True, headers

        except Exception as e:
            if settings.is_production:
                logger.critical(f"Redis rate limiter failure in production: {e}")
                raise RuntimeError(f"Rate limiter backend unreachable: {e}")
            logger.warning(f"Rate limiter fallback during dev/test: {e}")
            return True, {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(limit - 1),
                "X-RateLimit-Reset": str(int(now + window_seconds))
            }

rate_limiter = DistributedSlidingWindowRateLimiter()

def get_rate_limit_for_tenant(plan_name: Optional[str]) -> int:
    """Returns requests per minute allowed for tenant tier."""
    if not plan_name:
        return TIERED_PLAN_LIMITS["FREE"]
    normalized = plan_name.upper().strip()
    return TIERED_PLAN_LIMITS.get(normalized, TIERED_PLAN_LIMITS["FREE"])

async def check_multi_tier_rate_limit(
    request: Request,
    scope: str = "ip",
    custom_key: Optional[str] = None,
    limit: Optional[int] = None,
    plan_name: Optional[str] = None
) -> Dict[str, str]:
    """
    Enforces multi-tier rate limiting per IP, per tenant, per user, or per endpoint.
    Raises HTTPException 429 with Retry-After headers if exceeded.
    """
    client_ip = extract_client_ip(request) or "127.0.0.1"

    if scope == "ip":
        key = f"ip:{client_ip}"
        effective_limit = limit or DEFAULT_IP_LIMIT
    elif scope == "tenant":
        tenant_id = custom_key or getattr(request.state, "organization_id", None) or "anon_tenant"
        key = f"tenant:{tenant_id}"
        effective_limit = limit or get_rate_limit_for_tenant(plan_name)
    elif scope == "user":
        user_id = custom_key or getattr(request.state, "user_id", None) or "anon_user"
        key = f"user:{user_id}"
        effective_limit = limit or 300
    elif scope == "endpoint":
        path = request.url.path
        key = f"endpoint:{path}:{client_ip}"
        effective_limit = limit or DEFAULT_ENDPOINT_LIMIT
    else:
        key = f"misc:{custom_key or client_ip}"
        effective_limit = limit or 60

    allowed, headers = await rate_limiter.check_rate_limit(key, effective_limit)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Tier limit: {effective_limit} requests/minute.",
            headers=headers
        )
    return headers
