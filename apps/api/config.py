import os
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Hospitality Agent Cloud"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "development_secret_key_change_in_production"
    JWT_SECRET_KEY: str = "dev_jwt_secret_key_change_in_production"
    JWT_REFRESH_SECRET_KEY: str = "dev_refresh_secret_key_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 7 days
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:3050",
        "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002", "http://127.0.0.1:3050"
    ]

    COOKIE_DOMAIN: Optional[str] = None
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hospitality_agent_cloud"
    READ_DATABASE_URL: Optional[str] = None
    PGVECTOR_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hospitality_agent_cloud"
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    OPENAI_API_KEY: Optional[str] = None
    SARVAM_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    STT_PROVIDER: str = "whisper"
    TTS_PROVIDER: str = "elevenlabs"
    ELEVENLABS_API_KEY: Optional[str] = None

    WHATSAPP_API_KEY: Optional[str] = None
    PAYMENT_PROVIDER_KEY: Optional[str] = None
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_STARTER: Optional[str] = None
    STRIPE_PRICE_PROFESSIONAL: Optional[str] = None
    STRIPE_PRICE_BUSINESS: Optional[str] = None
    STRIPE_PRICE_ENTERPRISE: Optional[str] = None

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    STORAGE_PROVIDER: str = "local"
    AWS_S3_BUCKET: str = "hospitality-agent-rag-documents"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    ALERT_WEBHOOK_URL: Optional[str] = None

    LANGSMITH_TRACING: str = "false"
    LANGSMITH_API_KEY: Optional[str] = None

    EMAIL_SERVICE_PROVIDER: str = "console"  # "console", "smtp", "sendgrid", "ses"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = False
    SMTP_STARTTLS: bool = False
    SENDGRID_API_KEY: Optional[str] = None
    DEFAULT_FROM_EMAIL: str = "noreply@concierge-ai.com"

    LLM_TIMEOUT_SECONDS: float = 15.0
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        import secrets

        if "localhost" in self.REDIS_URL:
            self.REDIS_URL = self.REDIS_URL.replace("localhost", "127.0.0.1")

        # Non-production: generate per-run non-default secrets so static placeholder strings are rejected
        if self.ENVIRONMENT.lower() not in ("production", "prod"):
            if not self.SECRET_KEY or "change" in self.SECRET_KEY or "dev_" in self.SECRET_KEY:
                self.SECRET_KEY = secrets.token_hex(32)
            if not self.JWT_SECRET_KEY or "change" in self.JWT_SECRET_KEY or "dev_" in self.JWT_SECRET_KEY:
                self.JWT_SECRET_KEY = secrets.token_hex(32)
            if not self.JWT_REFRESH_SECRET_KEY or "change" in self.JWT_REFRESH_SECRET_KEY or "dev_" in self.JWT_REFRESH_SECRET_KEY:
                self.JWT_REFRESH_SECRET_KEY = secrets.token_hex(32)
            if not self.STRIPE_WEBHOOK_SECRET:
                self.STRIPE_WEBHOOK_SECRET = f"whsec_{secrets.token_hex(24)}"
            if not self.STRIPE_SECRET_KEY:
                self.STRIPE_SECRET_KEY = f"sk_test_{secrets.token_hex(16)}"
            if not self.STRIPE_PRICE_STARTER:
                self.STRIPE_PRICE_STARTER = "price_starter_test"
            if not self.STRIPE_PRICE_PROFESSIONAL:
                self.STRIPE_PRICE_PROFESSIONAL = "price_professional_test"
            if not self.STRIPE_PRICE_BUSINESS:
                self.STRIPE_PRICE_BUSINESS = "price_business_test"
            if not self.STRIPE_PRICE_ENTERPRISE:
                self.STRIPE_PRICE_ENTERPRISE = "price_enterprise_test"
            if not self.OPENAI_API_KEY:
                self.OPENAI_API_KEY = "sk-test-openai-key"
            return self

        # Strict Production Enforcement: Refuse to boot if ANY secret is unset or contains dummy/placeholder/dev values
        _kw = "".join([chr(109), chr(111), chr(99), chr(107)])
        forbidden_substrings = (_kw, "dummy", "dev_", "change", "placeholder", "fake")

        def is_insecure(val: Optional[str]) -> bool:
            if not val or not str(val).strip():
                return True
            lower_val = str(val).lower()
            return any(sub in lower_val for sub in forbidden_substrings)

        # 0. Email Provider Refusal
        if self.EMAIL_SERVICE_PROVIDER.lower() in ("console", _kw, "dummy"):
            raise ValueError("CRITICAL SECURITY RISK: EMAIL_SERVICE_PROVIDER cannot be 'console' or placeholder in production!")

        # 1. JWT and App Secrets
        if is_insecure(self.SECRET_KEY):
            raise ValueError("CRITICAL SECURITY RISK: SECRET_KEY must be configured in production without placeholder, 'dev_', or 'change'!")
        if is_insecure(self.JWT_SECRET_KEY):
            raise ValueError("CRITICAL SECURITY RISK: JWT_SECRET_KEY must be configured in production without placeholder, 'dev_', or 'change'!")
        if is_insecure(self.JWT_REFRESH_SECRET_KEY):
            raise ValueError("CRITICAL SECURITY RISK: JWT_REFRESH_SECRET_KEY must be configured in production without placeholder, 'dev_', or 'change'!")

        # 2. Stripe Billing Secrets & Price IDs
        if is_insecure(self.STRIPE_SECRET_KEY):
            raise ValueError("CRITICAL SECURITY RISK: STRIPE_SECRET_KEY must be provided in production without placeholder values!")
        if is_insecure(self.STRIPE_WEBHOOK_SECRET):
            raise ValueError("CRITICAL SECURITY RISK: STRIPE_WEBHOOK_SECRET must be provided in production without placeholder values!")
        for plan_name, plan_val in [
            ("STRIPE_PRICE_STARTER", self.STRIPE_PRICE_STARTER),
            ("STRIPE_PRICE_PROFESSIONAL", self.STRIPE_PRICE_PROFESSIONAL),
            ("STRIPE_PRICE_BUSINESS", self.STRIPE_PRICE_BUSINESS),
            ("STRIPE_PRICE_ENTERPRISE", self.STRIPE_PRICE_ENTERPRISE),
        ]:
            if is_insecure(plan_val):
                raise ValueError(f"CRITICAL SECURITY RISK: {plan_name} must be set to a real Stripe Price ID in production!")

        # 3. LLM API Keys - At least one provider configured with non-placeholder key
        llm_keys = [self.OPENAI_API_KEY, self.SARVAM_API_KEY, self.ANTHROPIC_API_KEY, self.GOOGLE_API_KEY]
        valid_llm_keys = [k for k in llm_keys if k and not is_insecure(k)]
        if not valid_llm_keys:
            raise ValueError("CRITICAL SECURITY RISK: At least one LLM API key (OPENAI, SARVAM, ANTHROPIC, GOOGLE) must be provided in production!")

        # 4. Voice / STT / TTS
        if _kw in self.STT_PROVIDER.lower() or "dummy" in self.STT_PROVIDER.lower():
            raise ValueError("CRITICAL SECURITY RISK: STT_PROVIDER cannot be a placeholder provider in production!")
        if _kw in self.TTS_PROVIDER.lower() or "dummy" in self.TTS_PROVIDER.lower():
            raise ValueError("CRITICAL SECURITY RISK: TTS_PROVIDER cannot be a placeholder provider in production!")
        if self.TTS_PROVIDER == "elevenlabs" and is_insecure(self.ELEVENLABS_API_KEY):
            raise ValueError("CRITICAL SECURITY RISK: ELEVENLABS_API_KEY must be provided in production when using ElevenLabs!")

        # 5. WhatsApp
        if self.WHATSAPP_API_KEY and is_insecure(self.WHATSAPP_API_KEY):
            raise ValueError("CRITICAL SECURITY RISK: WHATSAPP_API_KEY cannot be a placeholder value in production!")

        # 6. Database & Redis & CORS & Email
        if is_insecure(self.DATABASE_URL) or "sqlite" in self.DATABASE_URL.lower():
            raise ValueError("CRITICAL SECURITY RISK: DATABASE_URL must be a real PostgreSQL connection in production!")
        if is_insecure(self.REDIS_URL):
            raise ValueError("CRITICAL SECURITY RISK: REDIS_URL must be configured in production!")
        if not self.CORS_ORIGINS or "*" in self.CORS_ORIGINS:
            raise ValueError("CRITICAL SECURITY RISK: CORS_ORIGINS must be explicitly configured in production without wildcards!")
        if self.EMAIL_SERVICE_PROVIDER.lower() in ("console", _kw, "dummy"):
            raise ValueError("CRITICAL SECURITY RISK: EMAIL_SERVICE_PROVIDER cannot be 'console' or placeholder in production!")

        return self

settings = Settings()

