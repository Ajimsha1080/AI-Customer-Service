import pytest
import base64
import time
from httpx import AsyncClient, ASGITransport
from apps.api.main import app

@pytest.mark.asyncio
async def test_long_org_name_registration_no_truncation_crash():
    """Verify registration with >30 char organization names does not crash with StringDataRightTruncationError."""
    long_org_name = "New Hospitality Group International Resorts & Spas"
    email = f"admin_long_org_{time.time()}@example.com"
    payload = {
        "email": email,
        "password": "Password123!",
        "full_name": "Executive Admin",
        "organization_name": long_org_name,
        "organization_slug": "new-hospitality-group-international-resorts-and-spas"
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/auth/register", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert len(data["user"]["organization_id"]) <= 36

@pytest.mark.asyncio
async def test_guest_chat_mismatched_org_id_rejected():
    """Verify /agents/{agent_id}/chat rejects requests where caller passes mismatched organization_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        mismatched_chat_res = await client.post("/api/v1/agents/agt_hostel_01/chat", json={
            "organization_id": "org_spoofed_victim_tenant",
            "property_id": "prop_azure_palm_resort",
            "message": "Hello Concierge"
        })
        assert mismatched_chat_res.status_code == 400
        assert "Mismatched organization_id" in mismatched_chat_res.json()["detail"]

@pytest.mark.asyncio
async def test_voice_tts_gtts_generation():
    """Verify TTS endpoint generates real spoken audio (base64 audio/mp3) via gTTS."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tts_res = await client.post("/api/v1/voice/tts", json={
            "text": "Welcome to Azure Palm Resort! Dinner is served at 8 PM.",
            "language": "English"
        })
        assert tts_res.status_code == 200
        data = tts_res.json()
        assert "audio_base64" in data
        assert data["format"] in ["audio/mp3", "audio/wav"]
        # Decode audio to ensure it is valid non-empty binary
        audio_bytes = base64.b64decode(data["audio_base64"])
        assert len(audio_bytes) > 500

@pytest.mark.asyncio
async def test_persistent_logout_revocation():
    """Verify refresh token revocation invalidates the token across refresh requests."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg_res = await client.post("/api/v1/auth/register", json={
            "email": f"user_logout_{time.time()}@example.com",
            "password": "Password123!",
            "full_name": "Logout Tester"
        })
        refresh_tok = reg_res.json()["refresh_token"]

        # Logout
        logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_tok})
        assert logout_res.status_code == 200

        # Try refreshing using revoked token
        ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_tok})
        assert ref_res.status_code == 401
        assert "revoked" in ref_res.json()["detail"].lower()
