import re
import math
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger("hospitality_agent_cloud.integrations.voice_pipeline")

PER_MINUTE_RATE_USD = 0.035  # $0.035 / minute for SIP/WebRTC + TTS/STT

# PCI DSS Card Data Patterns
PAN_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
CVV_REGEX = re.compile(r"\b(cvv|cvc|security code|security digits)[:\s]+(\d{3,4})\b", re.IGNORECASE)

class VoiceTelephonyPipeline:
    """
    Enterprise Voice & Telephony Pipeline:
    1. Mandatory audio recording consent chime enforcement.
    2. PCI DSS PAN/CVV redaction in voice transcripts.
    3. Per-minute telephony usage and cost metering.
    """
    def verify_recording_consent(self, consent_acknowledged: bool) -> bool:
        """Enforces two-party consent laws and recording disclosure requirement."""
        if not consent_acknowledged:
            logger.warning("[VoicePipeline] Call rejected: Guest did not acknowledge recording consent chime.")
            return False
        return True

    def redact_pci_data_from_transcript(self, transcript: str) -> str:
        """Masks primary account numbers (PAN) and CVV security codes per PCI DSS Requirement 3."""
        # Redact CVVs first
        redacted = CVV_REGEX.sub(r"\1 [REDACTED_CVV]", transcript)
        # Redact PANs (credit cards)
        redacted = PAN_REGEX.sub("[REDACTED_CARD_NUMBER]", redacted)
        return redacted

    def calculate_voice_session_cost(self, duration_seconds: int) -> Tuple[float, int]:
        """
        Calculates telephony cost based on 60-second billing increments.
        Returns: (cost_usd, billable_minutes)
        """
        billable_minutes = math.ceil(max(0, duration_seconds) / 60)
        cost_usd = round(billable_minutes * PER_MINUTE_RATE_USD, 4)
        return cost_usd, billable_minutes

voice_pipeline = VoiceTelephonyPipeline()
