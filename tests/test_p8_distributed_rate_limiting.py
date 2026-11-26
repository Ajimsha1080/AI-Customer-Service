import pytest
import time
import uuid
from fastapi import Request, HTTPException
from services.security.rate_limiter import (
    DistributedSlidingWindowRateLimiter,
    get_rate_limit_for_tenant,
    check_multi_tier_rate_limit,
    TIERED_PLAN_LIMITS
)

def test_p8_tiered_plan_limits():
    assert get_rate_limit_for_tenant("FREE") == 60
    assert get_rate_limit_for_tenant("STARTER") == 120
    assert get_rate_limit_for_tenant("PRO") == 300
    assert get_rate_limit_for_tenant("PROFESSIONAL") == 300
    assert get_rate_limit_for_tenant("ENTERPRISE") == 1000
    assert get_rate_limit_for_tenant(None) == 60

@pytest.mark.asyncio
async def test_p8_redis_sliding_window_rate_limiting():
    limiter = DistributedSlidingWindowRateLimiter()
    test_key = f"test_sw_{uuid.uuid4().hex[:8]}"
    limit = 3

    # Hits 1, 2, 3 should all be allowed
    allowed1, h1 = await limiter.check_rate_limit(test_key, limit=limit, window_seconds=60)
    assert allowed1 is True
    assert h1["X-RateLimit-Limit"] == "3"
    assert h1["X-RateLimit-Remaining"] == "2"

    allowed2, h2 = await limiter.check_rate_limit(test_key, limit=limit, window_seconds=60)
    assert allowed2 is True
    assert h2["X-RateLimit-Remaining"] == "1"

    allowed3, h3 = await limiter.check_rate_limit(test_key, limit=limit, window_seconds=60)
    assert allowed3 is True
    assert h3["X-RateLimit-Remaining"] == "0"

    # Hit 4 should be blocked (429)
    allowed4, h4 = await limiter.check_rate_limit(test_key, limit=limit, window_seconds=60)
    assert allowed4 is False
    assert h4["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in h4
    assert int(h4["Retry-After"]) >= 1

@pytest.mark.asyncio
async def test_p8_multi_tier_scope_enforcement():
    # Construct simulated Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/voice/tts",
        "headers": [(b"host", b"testserver")],
        "client": ("198.51.100.25", 54321),
    }
    request = Request(scope)

    # Tenant tier test
    tenant_id = f"org_tier_{uuid.uuid4().hex[:6]}"
    
    # Run requests up to limit=2
    h1 = await check_multi_tier_rate_limit(
        request, scope="tenant", custom_key=tenant_id, limit=2, plan_name="FREE"
    )
    assert h1["X-RateLimit-Remaining"] == "1"

    h2 = await check_multi_tier_rate_limit(
        request, scope="tenant", custom_key=tenant_id, limit=2, plan_name="FREE"
    )
    assert h2["X-RateLimit-Remaining"] == "0"

    # 3rd request must trigger 429
    with pytest.raises(HTTPException) as exc_info:
        await check_multi_tier_rate_limit(
            request, scope="tenant", custom_key=tenant_id, limit=2, plan_name="FREE"
        )

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"
