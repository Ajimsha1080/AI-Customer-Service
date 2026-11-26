import pytest
import asyncio
from pathlib import Path
from apps.api.config import settings
from services.common.redis_service import (
    get_redis_connection_params,
    get_redis_client,
    acquire_distributed_lock
)

REDIS_CONF_FILE = Path(__file__).parent.parent / "infra" / "docker" / "redis.conf"

def test_p3_redis_tls_and_auth_parameter_handling(monkeypatch):
    # 1. TLS Upgrade test
    monkeypatch.setattr(settings, "REDIS_TLS", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis.internal:6379/0")
    monkeypatch.setattr(settings, "REDIS_PASSWORD", "super_secret_pw")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    url, kwargs = get_redis_connection_params()
    assert url.startswith("rediss://"), "TLS flag must upgrade redis:// scheme to rediss://"
    assert kwargs.get("password") == "super_secret_pw"
    assert kwargs.get("max_connections") == settings.REDIS_MAX_CONNECTIONS

    # 2. Production auth enforcement test
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "REDIS_PASSWORD", None)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis.internal:6379/0")

    with pytest.raises(RuntimeError, match="Redis authentication.*required in production"):
        get_redis_connection_params()

def test_p3_redis_conf_durability_and_eviction():
    assert REDIS_CONF_FILE.exists(), "infra/docker/redis.conf must exist"
    with open(REDIS_CONF_FILE, "r", encoding="utf-8") as f:
        conf = f.read()

    assert "maxmemory-policy volatile-lru" in conf, "Must configure volatile-lru eviction policy"
    assert "appendonly yes" in conf, "Must configure AOF persistence (appendonly yes)"
    assert "appendfsync everysec" in conf, "Must configure fsync everysec for durability"
    assert "save 900 1" in conf, "Must configure RDB snapshotting"
    assert "protected-mode yes" in conf, "Must enforce protected-mode"

def test_p3_sentinel_and_cluster_config(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_SENTINEL_HOSTS", "sentinel1:26379,sentinel2:26379")
    monkeypatch.setattr(settings, "REDIS_SENTINEL_MASTER", "hac-master")
    monkeypatch.setattr(settings, "REDIS_CLUSTER_MODE", False)

    hosts = [
        (h.split(":")[0], int(h.split(":")[1]))
        for h in settings.REDIS_SENTINEL_HOSTS.split(",")
        if ":" in h
    ]
    assert hosts == [("sentinel1", 26379), ("sentinel2", 26379)]
    assert settings.REDIS_SENTINEL_MASTER == "hac-master"

@pytest.mark.asyncio
async def test_p3_distributed_lock_execution():
    lock_key = "test_p3_room_lock"
    
    # Successful lock acquisition yields lock token
    async with acquire_distributed_lock(lock_key, ttl_seconds=5) as lock_val:
        assert bool(lock_val) is True

        # Concurrent attempt should raise RuntimeError (timeout quickly)
        with pytest.raises(RuntimeError, match="Failed to acquire lock"):
            async with acquire_distributed_lock(lock_key, ttl_seconds=5, acquire_timeout=0.2):
                pass

    # After exiting block, lock should be free again
    async with acquire_distributed_lock(lock_key, ttl_seconds=5, acquire_timeout=0.2) as reacquired:
        assert bool(reacquired) is True
