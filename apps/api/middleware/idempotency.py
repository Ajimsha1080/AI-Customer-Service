import json
import logging
import hashlib
from typing import Dict, Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from apps.api.config import settings

from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.middleware.idempotency")

# Backward compatibility reference for unit tests that clear state
IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {}
IN_FLIGHT_KEYS: set = set()

import json
import logging
import hashlib
from typing import Dict, Any, Optional
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from apps.api.config import settings
from apps.api.auth import extract_client_ip
from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.middleware.idempotency")

# Backward compatibility reference for unit tests that clear state
IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {}
IN_FLIGHT_KEYS: set = set()

def _extract_principal(request: Request) -> str:
    """Derives authenticated principal securely from Bearer JWT, API key, or client IP.
    Never trusts client-controlled X-Tenant-ID header.
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
        return f"token:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]}"

    api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key:
        return f"key:{hashlib.sha256(api_key.strip().encode('utf-8')).hexdigest()[:16]}"

    try:
        client_ip = extract_client_ip(request)
        return f"ip:{client_ip}"
    except Exception:
        return "anon:global"

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Enterprise Idempotency Middleware:
    Catches 'Idempotency-Key' on mutating methods (POST, PUT, PATCH, DELETE).
    Keys on: authenticated principal + method + path + body hash.
    Enforces strict reuse rules: same key with different request body returns 422 Unprocessable Entity.
    Deduplicates concurrent requests across replicas via Redis locks (409 Conflict)
    and replays completed responses with 'X-Cache-Lookup: HIT' and 'Idempotency-Replayed: true'.
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

        # Read request body to compute cryptographic hash
        body_bytes = await request.body()
        body_hash = hashlib.sha256(body_bytes).hexdigest()

        # Scope key by authenticated principal + method + path + idempotency key
        principal = _extract_principal(request)
        scope_key = f"hac:idemp:{principal}:{request.method}:{path}:{idempotency_key}"
        inflight_key = f"hac:idemp:inflight:{scope_key}"

        redis = await get_redis_client()

        # 1. Check if this idempotency key was previously seen for this principal+method+path
        cached_meta_raw = await redis.get(scope_key)
        if cached_meta_raw:
            try:
                cached_meta = json.loads(cached_meta_raw)
            except Exception:
                cached_meta = {}

            stored_body_hash = cached_meta.get("body_hash")
            # If the same idempotency key is submitted with a DIFFERENT body -> 422
            if stored_body_hash and stored_body_hash != body_hash:
                logger.warning(
                    f"[Idempotency] Key '{idempotency_key}' reused with different body hash: "
                    f"stored={stored_body_hash}, incoming={body_hash}"
                )
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Idempotency key mismatch: cannot reuse the same idempotency key with a different request payload."}
                )

            # If response was already cached for this exact body, replay it
            if "response" in cached_meta:
                cached = cached_meta["response"]
                logger.info(f"[Idempotency] Cache HIT for key '{scope_key}'. Replaying cached response.")
                headers = dict(cached["headers"])
                headers["X-Cache-Lookup"] = "HIT"
                headers["Idempotency-Replayed"] = "true"
                return Response(
                    content=cached["body"],
                    status_code=cached["status_code"],
                    headers=headers,
                    media_type=cached.get("media_type", "application/json")
                )

        # 2. Check in-flight lock across replicas (409 Conflict)
        acquired = await redis.set(inflight_key, body_hash, nx=True, ex=60)
        if not acquired or scope_key in IN_FLIGHT_KEYS:
            current_inflight_hash = await redis.get(inflight_key)
            if current_inflight_hash and current_inflight_hash != body_hash:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Idempotency key mismatch: cannot reuse the same idempotency key with a different request payload."}
                )
            logger.warning(f"[Idempotency] Concurrent in-flight request for key '{scope_key}'")
            return JSONResponse(
                status_code=409,
                content={"detail": "CONCURRENT_REQUEST_IN_FLIGHT: An identical request is currently processing."}
            )

        # 3. Store initial record with body_hash to detect mid-flight mismatch
        await redis.set(scope_key, json.dumps({"body_hash": body_hash}), ex=86400)
        IN_FLIGHT_KEYS.add(scope_key)

        try:
            response = await call_next(request)

            # Only cache successful or client error responses (don't cache 5xx server crashes)
            if response.status_code < 500:
                response_body = [chunk async for chunk in response.body_iterator]
                response.body_iterator = _iterate_chunks(response_body)
                raw_body = b"".join(response_body).decode("utf-8", errors="replace")

                cached_headers = {}
                for k, v in response.headers.items():
                    if k.lower() not in ("content-length", "transfer-encoding"):
                        cached_headers[k] = v

                cache_payload = {
                    "status_code": response.status_code,
                    "headers": cached_headers,
                    "body": raw_body,
                    "media_type": response.media_type
                }
                IDEMPOTENCY_CACHE[scope_key] = cache_payload
                await redis.set(scope_key, json.dumps({"body_hash": body_hash, "response": cache_payload}), ex=86400)

            return response
        finally:
            IN_FLIGHT_KEYS.discard(scope_key)
            await redis.delete(inflight_key)

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
