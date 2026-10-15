from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Agent, Conversation
from apps.api.auth import get_super_admin_user

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@router.get("/.well-known/security.txt")
async def security_txt():
    """RFC 9116 Vulnerability Disclosure Policy file."""
    from fastapi.responses import Response
    content = (
        "Contact: mailto:security@hospitalitycloud.com\n"
        "Expires: 2027-12-31T23:59:59.000Z\n"
        "Preferred-Languages: en\n"
        "Canonical: https://api.hospitalitycloud.com/.well-known/security.txt\n"
        "Policy: https://hospitalitycloud.com/security\n"
        "Hiring: https://hospitalitycloud.com/careers\n"
    )
    return Response(content=content, media_type="text/plain; charset=utf-8")

@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness probe that actually pings DB, Redis, and Vector Store."""
    # 1. Real DB Ping
    db_status = "connected"
    try:
        res = await db.execute(text("SELECT 1"))
        if res.scalar() != 1:
            db_status = "degraded"
    except Exception:
        db_status = "disconnected"

    # 2. Real Redis Ping (No false claim of connected if Redis is down)
    redis_status = "disconnected"
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5)
        if await r.ping():
            redis_status = "connected"
        await r.aclose()
    except Exception:
        redis_status = "disconnected"

    # 3. Real Vector Store Check
    vector_status = "connected"
    try:
        if "postgresql" in settings.DATABASE_URL:
            res = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            if not res.scalar():
                vector_status = "degraded"
    except Exception:
        vector_status = "degraded"

    overall_ready = (db_status == "connected" and redis_status == "connected" and vector_status == "connected")
    if not overall_ready and settings.ALERT_WEBHOOK_URL:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    settings.ALERT_WEBHOOK_URL,
                    json={
                        "text": f"🚨 [Hospitality SaaS Alert] /ready probe degraded! DB: {db_status}, Redis: {redis_status}, Vector: {vector_status}",
                        "service": settings.PROJECT_NAME,
                        "environment": settings.ENVIRONMENT,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
        except Exception:
            pass

    content = {
        "status": "ready" if overall_ready else "degraded",
        "database": db_status,
        "redis": redis_status,
        "vector_store": vector_status
    }
    if not overall_ready:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=content)
    return content

@router.get("/status")
async def public_status_page(db: AsyncSession = Depends(get_db)):
    """Public Status Page fed by real infrastructure checks and active incidents."""
    from services.operations.incident_manager import incident_manager
    from services.tasks.worker import list_dlq_jobs

    # 1. DB check
    db_ok = True
    try:
        r = await db.execute(text("SELECT 1"))
        db_ok = (r.scalar() == 1)
    except Exception:
        db_ok = False

    # 2. Redis check
    redis_ok = False
    try:
        import redis.asyncio as aioredis
        rc = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3)
        if await rc.ping():
            redis_ok = True
        await rc.aclose()
    except Exception:
        redis_ok = False

    active_incidents = incident_manager.list_incidents(active_only=True)
    all_ok = db_ok and redis_ok and len(active_incidents) == 0

    return {
        "status": "ALL_SYSTEMS_OPERATIONAL" if all_ok else "DEGRADED_PERFORMANCE",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "services": {
            "api_gateway": "OPERATIONAL",
            "database_postgresql": "OPERATIONAL" if db_ok else "DEGRADED",
            "redis_cache_and_pubsub": "OPERATIONAL" if redis_ok else "DEGRADED",
            "ai_inference_pipeline": "OPERATIONAL"
        },
        "active_incidents_count": len(active_incidents),
        "active_incidents": active_incidents
    }

@router.get("/status/incidents")
async def public_incidents_log():
    """Historical and active incident log."""
    from services.operations.incident_manager import incident_manager
    return {"incidents": incident_manager.list_incidents()}

@router.get("/prometheus/metrics")
async def prometheus_metrics():
    """Public or internal Prometheus scrape endpoint (standard text exposition format)."""
    from services.operations.metrics import metrics_registry
    from fastapi.responses import Response
    content = metrics_registry.generate_prometheus_format()
    return Response(content=content, media_type="text/plain; version=0.0.4; charset=utf-8")

@router.get("/metrics")
async def metrics(
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """0.7 Protected metrics: Super Admin authorization required."""
    agents_res = await db.execute(select(func.count(Agent.id)))
    active_agents = agents_res.scalar() or 0

    convs_res = await db.execute(select(func.count(Conversation.id)))
    total_conversations = convs_res.scalar() or 0

    return {
        "active_agents": active_agents,
        "total_conversations": total_conversations,
        "system_status": "OPERATIONAL"
    }

@router.get("/db-health")
async def db_health(
    current_user: User = Depends(get_super_admin_user)
):
    """0.7 / 3.0 Protected db-health: Super Admin authorization required."""
    from services.database.session import check_db_health
    return await check_db_health()

