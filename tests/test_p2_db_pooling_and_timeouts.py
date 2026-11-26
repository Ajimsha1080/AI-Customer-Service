import pytest
from sqlalchemy import text
from apps.api.config import settings
from services.database.session import (
    _format_db_url,
    get_db,
    get_read_db,
    check_db_health,
    AsyncSessionLocal,
    AsyncReadSessionLocal
)

def test_p2_database_pool_configuration_settings():
    assert settings.DB_POOL_SIZE == 20, "Postgres pool_size must be 20"
    assert settings.DB_MAX_OVERFLOW == 10, "Postgres max_overflow must be 10"
    assert settings.DB_POOL_TIMEOUT == 30, "Postgres pool_timeout must be 30 seconds"
    assert settings.DB_STATEMENT_TIMEOUT_MS == 30000, "Postgres statement_timeout must be 30,000ms (30s)"
    assert hasattr(settings, "DATABASE_READ_REPLICA_URL")

def test_p2_format_db_url_and_connect_args():
    # Verify driver normalization
    pg_url = "postgresql://user:pass@host:5432/db"
    assert _format_db_url(pg_url) == "postgresql+asyncpg://user:pass@host:5432/db"
    
    sqlite_url = "sqlite:///local.db"
    assert _format_db_url(sqlite_url) == "sqlite+aiosqlite:///local.db"

    # Verify statement_timeout and pool configuration in simulated engine kwargs
    engine_kwargs = {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "connect_args": {"server_settings": {"statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS)}},
    }
    assert engine_kwargs["connect_args"]["server_settings"]["statement_timeout"] == "30000"
    assert engine_kwargs["pool_size"] == 20
    assert engine_kwargs["max_overflow"] == 10
    assert engine_kwargs["pool_timeout"] == 30

@pytest.mark.asyncio
async def test_p2_read_replica_and_health():
    # 1. Read session dependency
    async for read_session in get_read_db():
        res = await read_session.execute(text("SELECT 1"))
        assert res.scalar() == 1

    # 2. Write session dependency
    async for write_session in get_db():
        res = await write_session.execute(text("SELECT 1"))
        assert res.scalar() == 1

    # 3. Health check with pool metrics
    health = await check_db_health()
    assert health["status"] == "healthy"
    assert health["pool_size"] == 20
    assert health["max_overflow"] == 10
    assert "latency_ms" in health
