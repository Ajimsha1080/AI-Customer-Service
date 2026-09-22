import sys
import time
from typing import AsyncGenerator, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from apps.api.config import settings

class Base(DeclarativeBase):
    pass

def _format_db_url(url: str) -> str:
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    return url

# Primary Write Engine Initialization
write_db_url = _format_db_url(settings.DATABASE_URL)
engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
    "pool_pre_ping": True,
}

# Apply enterprise connection pool options for PostgreSQL
if "postgresql" in write_db_url:
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    })

engine = create_async_engine(write_db_url, **engine_kwargs)

# Read Replica Engine Initialization (Enterprise Read/Write Isolation)
read_db_url = _format_db_url(settings.READ_DATABASE_URL or settings.DATABASE_URL)
read_engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
    "pool_pre_ping": True,
}
if "postgresql" in read_db_url:
    read_engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    })

read_engine = create_async_engine(read_db_url, **read_engine_kwargs)

# Session Makers
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

AsyncReadSessionLocal = async_sessionmaker(
    bind=read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Enterprise Multi-Tenant Row-Level Security (RLS) Transaction Scope."""
    if "postgresql" in str(session.bind.url):
        await session.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

async def get_db(tenant_id: Optional[str] = None) -> AsyncGenerator[AsyncSession, None]:
    """Primary Write Database Dependency with Tenant Context scoping."""
    async with AsyncSessionLocal() as session:
        try:
            if tenant_id:
                await set_tenant_context(session, tenant_id)
            yield session
            if session.is_active:
                await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                if session.is_active:
                    await session.rollback()
            except Exception:
                pass
            await session.close()

async def get_read_db(tenant_id: Optional[str] = None) -> AsyncGenerator[AsyncSession, None]:
    """Read-Only Replica Database Dependency for high-performance read isolation."""
    async with AsyncReadSessionLocal() as session:
        try:
            if tenant_id:
                await set_tenant_context(session, tenant_id)
            yield session
        finally:
            await session.close()

async def check_db_health() -> dict:
    """Enterprise Database Health, Pool Status & Latency Monitoring."""
    start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT 1"))
            val = res.scalar()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "healthy" if val == 1 else "unhealthy",
            "latency_ms": latency_ms,
            "read_replica_configured": settings.READ_DATABASE_URL is not None,
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "latency_ms": round((time.perf_counter() - start) * 1000, 2)
        }
