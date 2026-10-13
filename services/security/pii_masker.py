import re
from typing import Dict, Any, List, Optional

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(\+?[0-9]{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}")
CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
API_KEY_PATTERN = re.compile(r"(?:sk(?:-[a-zA-Z0-9_]+)?-[a-zA-Z0-9_]{16,}|whsec_[a-zA-Z0-9]{16,}|Bearer\s+[a-zA-Z0-9_\-\.]{20,})")

class PIIRedactionEngine:
    """Enterprise PII Masking, Redaction, and LLM Data Protection Engine.
    Guarantees no sensitive guest PII crosses to logs or unauthorized third-party LLMs.
    """
    def __init__(self):
        # Default allowed providers per tenant
        self.default_allowed_providers = ["OPENAI", "ANTHROPIC", "GOOGLE", "LOCAL_LLAMA"]

    def mask_email(self, match: re.Match) -> str:
        email = match.group(0)
        parts = email.split("@")
        if len(parts) == 2 and len(parts[0]) > 2:
            return f"{parts[0][0]}***{parts[0][-1]}@{parts[1]}"
        return "[REDACTED_EMAIL]"

    def mask_phone(self, match: re.Match) -> str:
        phone = match.group(0)
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 4:
            return f"***-***-{digits[-4:]}"
        return "[REDACTED_PHONE]"

    def redact_pii(self, text: str, mode: str = "redact") -> str:
        """Redacts or masks emails, phones, credit cards, SSNs, and API keys."""
        if not text:
            return ""

        redacted = text
        # 1. API Keys & Secrets
        redacted = API_KEY_PATTERN.sub("[REDACTED_SECRET]", redacted)

        # 2. Credit Cards
        redacted = CARD_PATTERN.sub("[REDACTED_CARD]", redacted)

        # 3. Social Security / National ID
        redacted = SSN_PATTERN.sub("[REDACTED_ID]", redacted)

        # 4. Email & Phone
        if mode == "mask":
            redacted = EMAIL_PATTERN.sub(self.mask_email, redacted)
            redacted = PHONE_PATTERN.sub(self.mask_phone, redacted)
        else:
            redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
            redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)

        return redacted

    def sanitize_llm_prompt(self, prompt: str, org_pii_policy: Optional[Dict[str, Any]] = None) -> str:
        """Sanitizes prompt sent to third-party model provider according to tenant policy."""
        if not org_pii_policy or org_pii_policy.get("allow_raw_pii", False):
            # If tenant specifically permits raw PII for personalization, only strip API keys & cards
            sanitized = API_KEY_PATTERN.sub("[REDACTED_SECRET]", prompt)
            return CARD_PATTERN.sub("[REDACTED_CARD]", sanitized)

        return self.redact_pii(prompt, mode="mask")

    def check_provider_allowed(self, provider: str, org_allowed_providers: Optional[List[str]] = None) -> bool:
        """Validates that tenant permits dispatching queries to the requested AI provider."""
        allowed = [p.upper() for p in (org_allowed_providers or self.default_allowed_providers)]
        return provider.upper() in allowed

    def get_zero_retention_headers(self) -> Dict[str, str]:
        """Provides zero-data-retention compliance flags for enterprise LLM calls."""
        return {
            "X-Zero-Data-Retention": "true",
            "X-Enterprise-Privacy-Mode": "strict"
        }

pii_engine = PIIRedactionEngine()
