import os
import io
import base64
import struct
import math
import uuid
import hashlib
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError
import httpx

from apps.api.config import settings
from services.security.limiter import limiter
from services.operations.feature_flags import feature_flags
from services.resilience.tenant_limiter import enforce_tenant_fair_use_quota, tenant_limiter
from services.integrations.voice_pipeline import voice_pipeline
from services.database.session import get_db, set_tenant_context
from services.database.models import VoiceSession, Agent, AgentStatus, ApiKey

router = APIRouter(prefix="/api/v1/voice", tags=["Data Plane - Voice Gateway"])

TTS_AUDIO_CACHE = {}

class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "Malayalam"
    voice_id: Optional[str] = "anushka"

class VoiceSessionIngestRequest(BaseModel):
    conversation_id: str
    agent_id: str
    duration_seconds: int
    raw_transcript: str
    organization_id: Optional[str] = None
    property_id: Optional[str] = None
    consent_acknowledged: bool = True

def generate_synthetic_wav_audio(duration_sec=1.5, sample_rate=16000, freq=440.0) -> str:
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    import wave
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(num_samples):
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * i / sample_rate))
            wav_file.writeframes(struct.pack('<h', val))
    return base64.b64encode(buf.getvalue()).decode('utf-8')

async def get_tts_principal_and_org(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> str:
    """Authenticates TTS caller via guest session token, Bearer access token, or API key.
    Rejects anonymous calls and does not trust arbitrary client X-Tenant-ID headers."""
    # 1. Check API Key
    api_key_header = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if api_key_header:
        key_hash = hashlib.sha256(api_key_header.strip().encode("utf-8")).hexdigest()
        stmt_key = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        res_key = await db.execute(stmt_key)
        api_key_row = res_key.scalar_one_or_none()
        if not api_key_row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
        return api_key_row.organization_id

    # 2. Check Bearer token or cookie
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header[7:].strip()
    elif request.cookies.get("access_token"):
        raw_token = request.cookies.get("access_token")

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: guest session token, access token, or API key required."
        )

    # 3. Decode token
    try:
        payload = jwt.decode(
            raw_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False}
        )
        token_type = payload.get("token_type")
        if token_type not in ("guest_session", "access"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type for TTS endpoint. Must be guest_session or access token."
            )
        org_id = payload.get("org_id")
        if not org_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing organization context.")
        return org_id
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid authentication token: {e}")

@router.post("/tts")
@limiter.limit("20/minute")
async def text_to_speech_gateway(
    request: Request,
    req: TTSRequest,
    org_id: str = Depends(get_tts_principal_and_org),
    db: AsyncSession = Depends(get_db)
):
    # Enforce tenant fair-use quota
    rate_ok, rem_tokens, retry_sec = await tenant_limiter.consume(org_id=org_id, cost=1)
    if not rate_ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for tenant. Burst limit: {tenant_limiter.default_burst_capacity}.",
            headers={"Retry-After": str(retry_sec)}
        )

    # Meter TTS usage per tenant in Redis
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    char_count = len(req.text)
    await redis.incrby(f"hac:tts_usage:{org_id}:chars", char_count)
    await redis.incr(f"hac:tts_usage:{org_id}:requests")

    if feature_flags.is_kill_switch_active("kill_switch_voice") or not feature_flags.is_enabled("voice", org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Voice subsystem is disabled or kill switch engaged."
        )

    cache_key = f"{req.language}:{req.text.strip().lower()}"
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    redis_tts_key = f"hac:tts:{cache_key}"
    cached_redis = await redis.get(redis_tts_key)
    if cached_redis:
        return {"audio_base64": cached_redis, "format": "audio/mp3", "source": "INDIC_VOICE_TTS_CACHED"}
    if cache_key in TTS_AUDIO_CACHE:
        return {"audio_base64": TTS_AUDIO_CACHE[cache_key], "format": "audio/mp3", "source": "INDIC_VOICE_TTS_CACHED"}

    sarvam_key = os.getenv("SARVAM_API_KEY") or settings.SARVAM_API_KEY or ""
    lang_map = {
        "Malayalam": "ml-IN",
        "Hindi": "hi-IN",
        "Tamil": "ta-IN",
        "Telugu": "te-IN",
        "Kannada": "kn-IN",
        "English": "en-IN"
    }
    target_code = lang_map.get(req.language or "Malayalam", "ml-IN")
    if sarvam_key and not sarvam_key.startswith("placeholder") and not sarvam_key.startswith("dummy"):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                headers = {
                    "api-subscription-key": str(sarvam_key),
                    "Content-Type": "application/json"
                }
                payload = {
                    "inputs": [req.text[:400]],
                    "target_language_code": target_code,
                    "speaker": "anushka",
                    "model": "bulbul:v2"
                }
                res = await client.post("https://api.sarvam.ai/text-to-speech", json=payload, headers=headers)
                if res.status_code == 200:
                    audios = res.json().get("audios", [])
                    if audios and audios[0]:
                        TTS_AUDIO_CACHE[cache_key] = audios[0]
                        return {"audio_base64": audios[0], "format": "audio/wav", "source": "REAL_SARVAM_AI_TTS"}
        except Exception as e:
            print("SARVAM TTS EXCEPTION:", str(e))
            pass

    # Real Spoken Speech Synthesis via gTTS
    gtts_lang_map = {
        "Malayalam": "ml",
        "Hindi": "hi",
        "Tamil": "ta",
        "Telugu": "te",
        "Kannada": "kn",
        "English": "en"
    }
    g_lang = gtts_lang_map.get(req.language or "Malayalam", "ml")
    try:
        from gtts import gTTS
        clean_text = req.text[:350]
        tts = gTTS(text=clean_text, lang=g_lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        b64_audio = base64.b64encode(buf.getvalue()).decode('utf-8')
        TTS_AUDIO_CACHE[cache_key] = b64_audio
        return {"audio_base64": b64_audio, "format": "audio/mp3", "source": "REAL_GTTS_INDIC_VOICE"}
    except Exception as e:
        print("GTTS EXCEPTION:", str(e))

    synthetic_wav = generate_synthetic_wav_audio()
    TTS_AUDIO_CACHE[cache_key] = synthetic_wav
    return {"audio_base64": synthetic_wav, "format": "audio/wav", "source": "GUARANTEED_SYNTHETIC_WAV_TTS"}


@router.post("/sessions", dependencies=[Depends(enforce_tenant_fair_use_quota)])
async def record_voice_session(
    request: Request,
    req: VoiceSessionIngestRequest,
    db: AsyncSession = Depends(get_db)
):
    # Security Control (C8): Lookup agent and derive tenant/property server-side
    agent_stmt = select(Agent).where(Agent.id == req.agent_id)
    agent_res = await db.execute(agent_stmt)
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{req.agent_id}' not found."
        )
    if agent.status != AgentStatus.ACTIVE:
        status_val = agent.status.value if hasattr(agent.status, "value") else str(agent.status)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent '{req.agent_id}' is not active (status: {status_val})."
        )

    effective_org_id = agent.organization_id
    effective_prop_id = agent.property_id
    await set_tenant_context(db, effective_org_id)

    if feature_flags.is_kill_switch_active("kill_switch_voice") or not feature_flags.is_enabled("voice", org_id=effective_org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Voice subsystem is disabled or kill switch engaged."
        )

    # 1. Enforce recording consent chime
    if not voice_pipeline.verify_recording_consent(req.consent_acknowledged):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CONSENT_REQUIRED: Guest did not acknowledge recording consent chime."
        )

    # 2. Redact PCI DSS data from transcript
    clean_transcript = voice_pipeline.redact_pci_data_from_transcript(req.raw_transcript)

    # 3. Calculate telephony cost and billable minutes
    cost_usd, billable_mins = voice_pipeline.calculate_voice_session_cost(req.duration_seconds)

    # 4. Save VoiceSession to DB strictly bounded by derived tenant & property
    session_id = str(uuid.uuid4())
    v_session = VoiceSession(
        id=session_id,
        conversation_id=req.conversation_id,
        organization_id=effective_org_id,
        property_id=effective_prop_id,
        agent_id=agent.id,
        duration_seconds=req.duration_seconds,
        cost=cost_usd,
        status="COMPLETED"
    )
    db.add(v_session)
    await db.commit()

    return {
        "session_id": session_id,
        "clean_transcript": clean_transcript,
        "billable_minutes": billable_mins,
        "cost_usd": cost_usd,
        "status": "COMPLETED"
    }
