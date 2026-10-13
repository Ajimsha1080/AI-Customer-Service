import json
import logging
import hashlib
from typing import Dict, Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.middleware.idempotency")

# In-memory storage for idempotency: key -> {"status_code": int, "headers": dict, "body": str}
IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {}
IN_FLIGHT_KEYS: set = set()

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Enterprise Idempotency Middleware:
    Catches 'Idempotency-Key' on mutating methods (POST, PUT, PATCH, DELETE).
    Deduplicates concurrent requests (409 Conflict) and replays completed responses
    with 'X-Cache-Lookup: HIT' and 'Idempotency-Replayed: true'.
    """
    async def dispatch(self, request: Request, call_next):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        # Exclude streaming endpoints or auth login
        path = request.url.path
        if "/events" in path or "/stream" in path or "/ws" in path or "/login" in path:
            return await call_next(request)

        idempotency_key = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        org_id = request.headers.get("X-Tenant-ID", "global")
        cache_key = f"idem:{org_id}:{idempotency_key}"

        # 1. Check if identical request is currently in-flight
        if cache_key in IN_FLIGHT_KEYS:
            logger.warning(f"[Idempotency] Concurrent in-flight request for key '{cache_key}'")
            return JSONResponse(
                status_code=409,
                content={"detail": "CONCURRENT_REQUEST_IN_FLIGHT: An identical request is currently processing."}
            )

        # 2. Check if already successfully resolved
        cached = IDEMPOTENCY_CACHE.get(cache_key)
        if cached:
            logger.info(f"[Idempotency] Cache HIT for key '{cache_key}'. Replaying cached response.")
            headers = dict(cached["headers"])
            headers["X-Cache-Lookup"] = "HIT"
            headers["Idempotency-Replayed"] = "true"
            return Response(
                content=cached["body"],
                status_code=cached["status_code"],
                headers=headers,
                media_type=cached.get("media_type", "application/json")
            )

        # 3. Process new request
        IN_FLIGHT_KEYS.add(cache_key)
        try:
            response = await call_next(request)

            # Only cache successful or client error responses (don't cache 5xx server crashes)
            if response.status_code < 500:
                # Capture body
                response_body = [chunk async for chunk in response.body_iterator]
                response.body_iterator = _iterate_chunks(response_body)
                raw_body = b"".join(response_body).decode("utf-8", errors="replace")

                cached_headers = {}
                for k, v in response.headers.items():
                    if k.lower() not in ("content-length", "transfer-encoding"):
                        cached_headers[k] = v

                IDEMPOTENCY_CACHE[cache_key] = {
                    "status_code": response.status_code,
                    "headers": cached_headers,
                    "body": raw_body,
                    "media_type": response.media_type
                }

            return response
        finally:
            IN_FLIGHT_KEYS.discard(cache_key)

async def _iterate_chunks(chunks):
    for c in chunks:
        yield c

def verify_etag_concurrency(current_version: int, if_match_header: Optional[str]) -> bool:
    """
    Optimistic concurrency validator:
    Compares resource version against client 'If-Match' header (e.g. W/"v3" or "3").
    Returns True if match, False if version conflict.
    """
    if not if_match_header:
        return True  # If client did not specify, optimistic concurrency is not enforced
    clean_header = if_match_header.strip().strip('"').lstrip('W/').strip('"')
    return clean_header == str(current_version)
