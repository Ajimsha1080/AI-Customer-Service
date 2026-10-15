import json
import logging
import uuid
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from apps.api.config import settings
from services.realtime.broadcaster import live_broadcaster
from services.database.session import get_db
from services.billing.metering import SaaSMeteringService

metering_service = SaaSMeteringService()

from services.security.limiter import limiter

# Configure Logging
logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger("hospitality_agent_cloud")

# Configure Sentry Error Tracking
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[FastApiIntegration()]
        )
    except Exception as e:
        logging.warning(f"Failed to initialize Sentry SDK: {e}")

from contextlib import asynccontextmanager
from services.realtime.broadcaster import realtime_hub

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production:
        from services.database.session import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector';"))
            if not res.scalar():
                raise RuntimeError("CRITICAL: pgvector extension is required in production database!")
    await realtime_hub.start_redis_subscriber()
    yield
    await realtime_hub.stop_redis_subscriber()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Multi-Tenant Autonomous Hospitality Agent Cloud Platform API (Argon2 Auth, Tenant Scoping, PGVector RAG, LiteLLM Agent Loop, Billing Enforcement).",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- RATE LIMITING MIDDLEWARE ---
from slowapi.middleware import SlowAPIMiddleware
app.add_middleware(SlowAPIMiddleware)

from apps.api.middleware.idempotency import IdempotencyMiddleware
app.add_middleware(IdempotencyMiddleware)

from services.operations.metrics import PrometheusMetricsMiddleware
app.add_middleware(PrometheusMetricsMiddleware)

from apps.api.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# --- CORS MIDDLEWARE HARDENING ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# --- REQUEST ID & STRUCTURED LOGGING MIDDLEWARE ---
import re

@app.middleware("http")
async def request_id_and_logging_middleware(request: Request, call_next):
    raw_request_id = request.headers.get("X-Request-ID", "").strip()
    if raw_request_id and re.match(r"^[a-zA-Z0-9_\-]{1,64}$", raw_request_id):
        request_id = raw_request_id
    else:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

    start_time = time.time()
    response = await call_next(request)
    latency_ms = round((time.time() - start_time) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    if getattr(request.state, "is_support_impersonation", False):
        response.headers["X-Support-Impersonation"] = "Active"

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "latency_ms": latency_ms
    }
    logger.info(json.dumps(log_entry))
    return response

# --- ERROR HANDLERS ---
@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: Exception):
    status_code = getattr(exc, "status_code", 400)
    detail = getattr(exc, "detail", str(exc))
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    resp_headers = {"X-Request-ID": request_id}
    exc_headers = getattr(exc, "headers", None)
    if exc_headers and isinstance(exc_headers, dict):
        resp_headers.update(exc_headers)
    return JSONResponse(
        status_code=status_code,
        headers=resp_headers,
        content={
            "detail": str(detail),
            "error": {
                "code": "HTTP_ERROR",
                "status_code": status_code,
                "message": str(detail),
                "request_id": request_id
            }
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers={"X-Request-ID": request_id},
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "status_code": 500,
                "message": "An unexpected system error occurred. Our operations team has been notified.",
                "request_id": request_id
            }
        }
    )

from apps.api.routers import (
    health, auth, agents, voice, billing, integrations, platform, conversations,
    organizations, hospitality_crud, mfa, sessions, sso, scim, custom_roles, gdpr,
    developer, email_webhooks
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(mfa.router)
app.include_router(sessions.router)
app.include_router(sso.router)
app.include_router(scim.router)
app.include_router(custom_roles.router)
app.include_router(gdpr.router)
app.include_router(developer.router)
app.include_router(organizations.router)
app.include_router(agents.router)
app.include_router(voice.router)
app.include_router(billing.router)
app.include_router(integrations.router)
app.include_router(platform.router)
app.include_router(conversations.router)
app.include_router(hospitality_crud.router)
app.include_router(email_webhooks.router)


