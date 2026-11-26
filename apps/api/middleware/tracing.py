import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.access")

def extract_trace_id(request: Request) -> str:
    """Extracts W3C traceparent trace_id or X-Trace-ID, or generates a new 32-char hex trace_id."""
    traceparent = request.headers.get("traceparent", "").strip()
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1]

    header_trace = request.headers.get("X-Trace-ID", "").strip()
    if header_trace and re.match(r"^[a-fA-F0-9]{16,64}$", header_trace):
        return header_trace

    return uuid.uuid4().hex

def extract_tenant_id(request: Request) -> str:
    """Extracts tenant_id from request state, auth token, or header."""
    if hasattr(request.state, "tenant_id") and request.state.tenant_id:
        return str(request.state.tenant_id)
    if hasattr(request.state, "organization_id") and request.state.organization_id:
        return str(request.state.organization_id)

    header_tenant = request.headers.get("X-Tenant-ID", "").strip()
    if header_tenant and re.match(r"^[a-zA-Z0-9_\-]{1,64}$", header_tenant):
        return header_tenant

    return "anonymous"

class TracingAndLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured JSON Logging & Distributed Tracing Middleware.
    Emits structured JSON logs containing trace_id and tenant_id on every single entry.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = extract_trace_id(request)
        raw_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = raw_request_id if (raw_request_id and re.match(r"^[a-zA-Z0-9_\-]{1,64}$", raw_request_id)) else f"req_{uuid.uuid4().hex[:12]}"

        request.state.trace_id = trace_id
        request.state.request_id = request_id

        start_time = time.perf_counter()
        response: Response = await call_next(request)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        tenant_id = extract_tenant_id(request)

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-ID"] = request_id

        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "request_id": request_id,
            "tenant_id": tenant_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "client_ip": request.client.host if request.client else "unknown"
        }
        logger.info(json.dumps(log_record))
        return response

def setup_opentelemetry(app, service_name: str = "hospitality-agent-cloud"):
    """Configures OpenTelemetry distributed tracing instrumentation for FastAPI, SQLAlchemy, Redis, and HTTPX."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        RedisInstrumentor().instrument()
        from services.database.session import engine
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info(f"OpenTelemetry distributed tracing configured for service: {service_name}")
        return True
    except ImportError:
        logger.debug("OpenTelemetry optional packages not installed; skipping instrumentation hooks.")
        return False
    except Exception as e:
        logger.warning(f"OpenTelemetry instrumentation warning: {e}")
        return False
