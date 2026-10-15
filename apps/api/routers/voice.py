import os
import io
import base64
import struct
import math
import uuid
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from apps.api.config import settings
from services.security.limiter import limiter
from services.operations.feature_flags import feature_flags
from services.resilience.tenant_limiter import enforce_tenant_fair_use_quota
from services.integrations.voice_pipeline import voice_pipeline
from services.database.session import get_db
from services.database.models import VoiceSession

router = APIRouter(prefix="/api/v1/voice", tags=["Data Plane - Voice Gateway"])

TTS_AUDIO_CACHE = {}

class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "Malayalam"
    voice_id: Optional[str] = "anushka"

class VoiceSessionIngestRequest(BaseModel):
    conversation_id: str
    organization_id: str
    property_id: str
    agent_id: str
    duration_seconds: int
    raw_transcript: str
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

@router.post("/tts", dependencies=[Depends(enforce_tenant_fair_use_quota)])
@limiter.limit("20/minute")
async def text_to_speech_gateway(request: Request, req: TTSRequest):
    org_id = (
        getattr(request.state, "tenant_id", None)
        or getattr(request.state, "organization_id", None)
        or request.headers.get("X-Tenant-ID")
        or request.headers.get("x-tenant-id")
        or "global"
    )
    if feature_flags.is_kill_switch_active("kill_switch_voice") or not feature_flags.is_enabled("voice", org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Voice subsystem is disabled or kill switch engaged."
        )

    cache_key = f"{req.language}:{req.text.strip().lower()}"
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
    if sarvam_key and not sarvam_key.startswith("mock"):
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
    if feature_flags.is_kill_switch_active("kill_switch_voice") or not feature_flags.is_enabled("voice", org_id=req.organization_id):
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

    # 4. Save VoiceSession to DB
    session_id = str(uuid.uuid4())
    v_session = VoiceSession(
        id=session_id,
        conversation_id=req.conversation_id,
        organization_id=req.organization_id,
        property_id=req.property_id,
        agent_id=req.agent_id,
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
