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

    overall_ready = (db_status == "connected" and redis_status == "connected")
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

    return {
        "status": "ready" if overall_ready else "degraded",
        "database": db_status,
        "redis": redis_status,
        "vector_store": vector_status
    }

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
