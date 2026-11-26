import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password, create_guest_session_token
from services.database.models import User, Organization, UserRole, ApiKey, Agent, AgentStatus, AgentType, Property
from services.common.redis_service import get_redis_client

@pytest.mark.asyncio
async def test_h12_tts_rejects_unauthenticated_and_untrusted_header(db_session):
    """H12: /api/v1/voice/tts is no longer public and does not trust X-Tenant-ID."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Anonymous request without token is rejected with 401
        res = await ac.post("/api/v1/voice/tts", json={"text": "Hello world", "language": "English"})
        assert res.status_code == 401

        # 2. Anonymous request passing arbitrary X-Tenant-ID is rejected with 401
        res2 = await ac.post(
            "/api/v1/voice/tts",
            headers={"X-Tenant-ID": "fake_org_id"},
            json={"text": "Hello world", "language": "English"}
        )
        assert res2.status_code == 401

@pytest.mark.asyncio
async def test_h12_tts_authenticates_guest_token_and_meters_usage(db_session):
    """H12: TTS accepts signed guest token and meters per-tenant character usage in Redis."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="TTS Meter Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop = Property(id=str(uuid.uuid4()), organization_id=org_id, name="TTS Resort")
        agent = Agent(id=str(uuid.uuid4()), organization_id=org_id, property_id=prop.id, name="TTS Agent", status=AgentStatus.ACTIVE)
        db_session.add(org)
        db_session.add(prop)
        db_session.add(agent)
        await db_session.commit()

        # Generate guest session token
        guest_token = create_guest_session_token(
            conversation_id=str(uuid.uuid4()),
            organization_id=org_id
        )

        test_text = "Welcome to our luxury resort! How may I assist your stay today?"
        res = await ac.post(
            "/api/v1/voice/tts",
            headers={"Authorization": f"Bearer {guest_token}"},
            json={"text": test_text, "language": "English"}
        )
        assert res.status_code == 200
        assert "audio_base64" in res.json()

        # Verify Redis metering for this tenant
        redis = await get_redis_client()
        chars_used = await redis.get(f"hac:tts_usage:{org_id}:chars")
        assert chars_used is not None
        assert int(chars_used) >= len(test_text)

        requests_count = await redis.get(f"hac:tts_usage:{org_id}:requests")
        assert requests_count is not None
        assert int(requests_count) >= 1

@pytest.mark.asyncio
async def test_h12_metrics_internal_only_restriction(db_session):
    """H12: /metrics and /prometheus/metrics are restricted to internal network or Super Admin."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. External IP without auth is strictly forbidden (403)
        ext_headers = {"X-Forwarded-For": "93.184.216.34"}
        res_prom = await ac.get("/api/v1/prometheus/metrics", headers=ext_headers)
        assert res_prom.status_code == 403
        assert "Access denied" in res_prom.json()["detail"]

        res_metrics = await ac.get("/api/v1/metrics", headers=ext_headers)
        assert res_metrics.status_code == 403
        assert "Access denied" in res_metrics.json()["detail"]

        # 2. Internal loopback or private IP succeeds
        int_headers = {"X-Forwarded-For": "10.0.1.5"}
        res_prom_internal = await ac.get("/api/v1/prometheus/metrics", headers=int_headers)
        assert res_prom_internal.status_code == 200

        # 3. Super Admin from external IP succeeds
        org_id = str(uuid.uuid4())
        super_admin = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"metrics_sa_{uuid.uuid4().hex[:6]}@platform.local",
            full_name="Metrics SuperAdmin",
            hashed_password=hash_password("pwd"),
            role=UserRole.SUPER_ADMIN,
            is_active=True
        )
        db_session.add(super_admin)
        await db_session.commit()

        sa_token = create_access_token({"sub": super_admin.id, "org_id": org_id, "role": "SUPER_ADMIN", "test_synthetic": True})
        ext_sa_headers = {
            "X-Forwarded-For": "93.184.216.34",
            "Authorization": f"Bearer {sa_token}"
        }
        res_sa = await ac.get("/api/v1/metrics", headers=ext_sa_headers)
        assert res_sa.status_code == 200
        assert "active_agents" in res_sa.json()
