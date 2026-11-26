import json
import logging
import os
import time
from typing import Dict, Any, Optional
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.secrets")

PLACEHOLDER_SUBSTRINGS = [
    "change_me", "changeme", "default", "placeholder", "dummy",
    "secret_key_default", "your-secret-key", "test_secret", "example"
]

CRITICAL_PROD_SECRETS = [
    "SECRET_KEY",
    "DATABASE_URL",
    "REDIS_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "WHATSAPP_APP_SECRET"
]

def is_placeholder_secret(val: Optional[str]) -> bool:
    """Returns True if the secret value is empty, unset, or matches known placeholder patterns."""
    if not val or not isinstance(val, str):
        return True
    lower = val.lower().strip()
    if len(lower) < 16:
        return True
    return any(sub in lower for sub in PLACEHOLDER_SUBSTRINGS)

def validate_production_secrets(config=None) -> None:
    """
    Enforces that all critical production credentials are set, non-empty,
    and non-placeholder. Fails fast with RuntimeError at application startup.
    """
    cfg = config or settings
    if not cfg.is_production:
        return

    missing_or_insecure = []
    for secret_name in CRITICAL_PROD_SECRETS:
        val = getattr(cfg, secret_name, None)
        if not val or is_placeholder_secret(val):
            missing_or_insecure.append(secret_name)

    if missing_or_insecure:
        err_msg = (
            f"FATAL: Production startup blocked. Missing or insecure placeholder secrets: "
            f"{', '.join(missing_or_insecure)}. Real production credentials required."
        )
        logger.critical(err_msg)
        raise RuntimeError(err_msg)

class SecretsManagerService:
    """
    Unified Secrets Manager client supporting AWS Secrets Manager and HashiCorp Vault
    with TTL caching and dynamic secret rotation.
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._provider = getattr(settings, "SECRETS_PROVIDER", "aws").lower()

    def get_secret(self, secret_id: str, force_refresh: bool = False) -> str:
        """Retrieves a secret with cache check or dynamic provider fetch."""
        now = time.time()
        if not force_refresh and secret_id in self._cache:
            entry = self._cache[secret_id]
            if now - entry["fetched_at"] < self.cache_ttl_seconds:
                return entry["value"]

        val = self._fetch_from_provider(secret_id)
        self._cache[secret_id] = {"value": val, "fetched_at": now}
        return val

    def invalidate_cache(self, secret_id: Optional[str] = None) -> None:
        """Evicts cached secrets to force fresh rotation retrieval."""
        if secret_id:
            self._cache.pop(secret_id, None)
        else:
            self._cache.clear()

    def rotate_secret(self, secret_id: str, new_value: Optional[str] = None) -> str:
        """Dynamically rotates a secret by invalidating cache and fetching latest version."""
        self.invalidate_cache(secret_id)
        if new_value:
            self._cache[secret_id] = {"value": new_value, "fetched_at": time.time()}
            return new_value
        return self.get_secret(secret_id, force_refresh=True)

    def _fetch_from_provider(self, secret_id: str) -> str:
        """Fetches raw secret string from AWS Secrets Manager or HashiCorp Vault."""
        if self._provider == "vault":
            return self._fetch_from_vault(secret_id)
        return self._fetch_from_aws(secret_id)

    def _fetch_from_aws(self, secret_id: str) -> str:
        try:
            import boto3
            client = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
            response = client.get_secret_value(SecretId=secret_id)
            return response.get("SecretString", "")
        except Exception as e:
            if settings.is_production:
                raise RuntimeError(f"AWS Secrets Manager failed for '{secret_id}': {e}")
            return f"mock_secret_for_{secret_id}"

    def _fetch_from_vault(self, secret_id: str) -> str:
        try:
            import httpx
            vault_addr = getattr(settings, "VAULT_ADDR", "http://127.0.0.1:8200")
            vault_token = getattr(settings, "VAULT_TOKEN", "")
            with httpx.Client(timeout=5.0) as client:
                res = client.get(
                    f"{vault_addr}/v1/secret/data/{secret_id}",
                    headers={"X-Vault-Token": vault_token}
                )
                if res.status_code == 200:
                    data = res.json().get("data", {}).get("data", {})
                    return json.dumps(data)
                raise RuntimeError(f"Vault error HTTP {res.status_code}")
        except Exception as e:
            if settings.is_production:
                raise RuntimeError(f"Vault failed for '{secret_id}': {e}")
            return f"mock_vault_secret_{secret_id}"

secrets_service = SecretsManagerService()
