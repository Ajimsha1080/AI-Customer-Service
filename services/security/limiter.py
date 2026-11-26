import sys
from fastapi import Request
from slowapi import Limiter

from apps.api.config import settings
from apps.api.auth import extract_client_ip

def get_real_client_ip(request: Request) -> str:
    """Extracts client IP using trusted-proxy handling."""
    ip = extract_client_ip(request)
    return ip or "127.0.0.1"

import sys
from fastapi import Request
from slowapi import Limiter

from apps.api.config import settings
from apps.api.auth import extract_client_ip

def get_real_client_ip(request: Request) -> str:
    """Extracts client IP using trusted-proxy handling."""
    ip = extract_client_ip(request)
    return ip or "127.0.0.1"

def _get_storage_uri() -> str:
    """Returns Redis storage URI in production, or fallback to memory in dev/test when Redis is unreachable."""
    if settings.is_production:
        return settings.REDIS_URL
    try:
        import redis
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.2)
        client.ping()
        return settings.REDIS_URL
    except Exception:
        return "memory://"

# Rate limiter keys on the real client IP with Redis storage
limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=["100/minute"],
    storage_uri=_get_storage_uri(),
    strategy="fixed-window",
    enabled=True
)
