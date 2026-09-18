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

# Configure Limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Configure Logging
logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger("hospitality_agent_cloud")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Multi-Tenant Autonomous Hospitality Agent Cloud Platform API (Argon2 Auth, Tenant Scoping, PGVector RAG, LiteLLM Agent Loop, Billing Enforcement)."
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS MIDDLEWARE HARDENING ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# --- REQUEST ID & STRUCTURED LOGGING MIDDLEWARE ---
@app.middleware("http")
async def request_id_and_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

    start_time = time.time()
    response = await call_next(request)
    latency_ms = round((time.time() - start_time) * 1000, 2)

    response.headers["X-Request-ID"] = request_id

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
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id},
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

# --- INCLUDE ROUTERS ---
from apps.api.routers import (
    health, auth, agents, voice, billing, integrations, platform, conversations, organizations
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(agents.router)
app.include_router(voice.router)
app.include_router(billing.router)
app.include_router(integrations.router)
app.include_router(platform.router)
app.include_router(conversations.router)


async def init_db_and_seed():
    from services.database.session import AsyncSessionLocal, engine, Base
    import services.database.models
    from services.database.models import User, Organization, UserRole
    from apps.api.auth import hash_password
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        res_org = await db.execute(select(Organization).where(Organization.id == "org_azure_group"))
        org = res_org.scalar_one_or_none()
        if not org:
            org = Organization(id="org_azure_group", name="Azure Palm Hostel", slug="azure-palm-hostel")
            db.add(org)
            await db.flush()

        users_to_seed = [
            ("usr_admin_01", "admin@azurehostel.com", UserRole.ORGANIZATION_ADMIN, "admin123"),
            ("usr_demo123", "demo@azurehostel.com", UserRole.ORGANIZATION_ADMIN, "admin123"),
            ("usr_superadmin", "superadmin@azurehostel.com", UserRole.SUPER_ADMIN, "superadmin123"),
        ]

        for u_id, email, role, pwd in users_to_seed:
            res_u = await db.execute(select(User).where(User.id == u_id))
            if not res_u.scalar_one_or_none():
                u_obj = User(
                    id=u_id,
                    organization_id=org.id,
                    email=email,
                    hashed_password=hash_password(pwd),
                    full_name=email.split("@")[0].title(),
                    role=role,
                    is_active=True
                )
                db.add(u_obj)
        await db.commit()
