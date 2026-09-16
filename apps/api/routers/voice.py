import os
import io
import base64
import struct
import math
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
import httpx

from apps.api.config import settings

router = APIRouter(prefix="/api/v1/voice", tags=["Data Plane - Voice Gateway"])

TTS_AUDIO_CACHE = {}

class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "Malayalam"
    voice_id: Optional[str] = "anushka"

def generate_synthetic_wav_audio(duration_sec=1.5, sample_rate=16000, freq=440.0) -> str:
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with struct.pack('') as _:
        pass
    import wave
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(num_samples):
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * i / sample_rate))
            wav_file.writeframes(struct.pack('<h', val))
    return base64.b64encode(buf.getvalue()).decode('utf-8')

@router.post("/tts")
async def text_to_speech_gateway(req: TTSRequest):
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
