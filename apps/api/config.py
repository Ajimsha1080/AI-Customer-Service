import os
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Hospitality Agent Cloud"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "development_secret_key_change_in_production"
    JWT_SECRET_KEY: str = "dev_jwt_secret_key_change_in_production"
    JWT_REFRESH_SECRET_KEY: str = "dev_refresh_secret_key_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 7 days
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hospitality_agent_cloud"
    READ_DATABASE_URL: Optional[str] = None
    PGVECTOR_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hospitality_agent_cloud"
    REDIS_URL: str = "redis://localhost:6379/0"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    OPENAI_API_KEY: Optional[str] = "sk-mock-openai-key-for-dev"
    SARVAM_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = "sk-mock-anthropic-key-for-dev"
    GOOGLE_API_KEY: Optional[str] = "mock-google-key-for-dev"

    STT_PROVIDER: str = "whisper_mock"
    TTS_PROVIDER: str = "elevenlabs_mock"
    ELEVENLABS_API_KEY: Optional[str] = "mock-elevenlabs-key"

    WHATSAPP_API_KEY: Optional[str] = "mock-whatsapp-key"
    PAYMENT_PROVIDER_KEY: Optional[str] = "mock-stripe-key"
    STRIPE_SECRET_KEY: Optional[str] = "sk_test_mock_stripe_key"
    STRIPE_WEBHOOK_SECRET: Optional[str] = "whsec_mock_stripe_webhook_secret"
    STRIPE_PRICE_STARTER: str = "price_starter_mock"
    STRIPE_PRICE_PROFESSIONAL: str = "price_professional_mock"
    STRIPE_PRICE_BUSINESS: str = "price_business_mock"
    STRIPE_PRICE_ENTERPRISE: str = "price_enterprise_mock"

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    STORAGE_PROVIDER: str = "local"
    AWS_S3_BUCKET: str = "hospitality-agent-rag-documents"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    SENTRY_DSN: Optional[str] = None

    LANGSMITH_TRACING: str = "false"
    LANGSMITH_API_KEY: Optional[str] = "mock-langsmith-key"

    LLM_TIMEOUT_SECONDS: float = 15.0
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT.lower() in ("production", "prod"):
            dev_secrets = {
                "development_secret_key_change_in_production",
                "dev_jwt_secret_key_change_in_production",
                "dev_refresh_secret_key_change_in_production",
                "",
                None
            }
            if self.SECRET_KEY in dev_secrets:
                raise ValueError("CRITICAL SECURITY RISK: SECRET_KEY must be provided via environment variable in production!")
            if self.JWT_SECRET_KEY in dev_secrets:
                raise ValueError("CRITICAL SECURITY RISK: JWT_SECRET_KEY must be provided via environment variable in production!")
            if self.JWT_REFRESH_SECRET_KEY in dev_secrets:
                raise ValueError("CRITICAL SECURITY RISK: JWT_REFRESH_SECRET_KEY must be provided via environment variable in production!")
        return self

settings = Settings()

