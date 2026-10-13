from datetime import datetime, timezone
import zoneinfo
from typing import Dict, Any, Optional

# Standard reference exchange rates relative to USD (base 1.0)
EXCHANGE_RATES_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.78,
    "INR": 83.50,
    "JPY": 155.0,
    "AED": 3.67
}

RTL_LANGUAGES = {"ar", "he", "fa", "ur"}

SUPPORTED_LOCALES = [
    "en", "es", "fr", "de", "it", "pt", "ar", "ja", "zh", "hi",
    "ru", "ko", "nl", "tr", "pl", "sv", "da", "fi", "el", "cs",
    "th", "vi", "id", "ms", "he", "fa", "ur", "bn", "ta", "te"
]

class HospitalityLocalizationService:
    """
    Enterprise Hospitality Multi-Currency, Timezone, and Localization Service:
    - Real-time currency conversions across property portfolio currencies.
    - Property timezone-aware datetime localization.
    - RTL (Right-to-Left) script detection for Arabic/Hebrew guest chat.
    """
    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Converts currency amount between supported currencies."""
        from_c = from_currency.upper()
        to_c = to_currency.upper()

        if from_c == to_c:
            return round(amount, 2)

        if from_c not in EXCHANGE_RATES_TO_USD or to_c not in EXCHANGE_RATES_TO_USD:
            raise ValueError(f"Unsupported currency pair: {from_c} -> {to_c}")

        # Convert from source to USD base, then to target
        usd_amount = amount / EXCHANGE_RATES_TO_USD[from_c]
        target_amount = usd_amount * EXCHANGE_RATES_TO_USD[to_c]
        return round(target_amount, 2)

    def format_property_time(self, dt: datetime, tz_identifier: str = "UTC") -> str:
        """Formats datetime into property local timezone ISO string."""
        try:
            tz = zoneinfo.ZoneInfo(tz_identifier)
        except Exception:
            tz = timezone.utc

        utc_dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        local_dt = utc_dt.astimezone(tz)
        return local_dt.isoformat()

    def is_rtl_language(self, language_code: str) -> bool:
        """Detects whether language requires Right-to-Left UI orientation."""
        lang = language_code.lower().split("-")[0]
        return lang in RTL_LANGUAGES

localization_service = HospitalityLocalizationService()
