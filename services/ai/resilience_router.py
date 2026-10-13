import hashlib
import time
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from services.resilience.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError

logger = logging.getLogger("hospitality_agent_cloud.ai.resilience_router")

class SpendCapExceededError(Exception):
    pass

class LLMResilienceRouter:
    """
    Enterprise LLM Resilience Router:
    1. Primary -> Secondary provider failover with circuit breakers.
    2. Per-tenant spend caps with alerting.
    3. Safe prompt/response caching.
    4. Deterministic degraded mode that never invents facts or writes data.
    """
    def __init__(self):
        self.primary_breaker = get_circuit_breaker("llm_primary", failure_threshold=3, recovery_timeout=5.0, call_timeout=5.0)
        self.secondary_breaker = get_circuit_breaker("llm_secondary", failure_threshold=3, recovery_timeout=5.0, call_timeout=5.0)
        # In-memory prompt cache: cache_key -> (response_text, expires_at)
        self._cache: Dict[str, tuple[str, float]] = {}
        # Per-tenant spend tracking: org_id -> float (USD)
        self._tenant_spend: Dict[str, float] = {}
        # Per-tenant spend caps: org_id -> float (USD)
        self._tenant_spend_caps: Dict[str, float] = {}

    def set_spend_cap(self, org_id: str, cap_usd: float):
        self._tenant_spend_caps[org_id] = cap_usd

    def record_spend(self, org_id: str, amount_usd: float):
        self._tenant_spend[org_id] = self._tenant_spend.get(org_id, 0.0) + amount_usd

    def get_spend(self, org_id: str) -> float:
        return self._tenant_spend.get(org_id, 0.0)

    def _get_cache_key(self, org_id: str, prompt: str) -> str:
        h = hashlib.sha256(f"{org_id}:{prompt.strip()}".encode("utf-8")).hexdigest()
        return f"llm_cache:{h}"

    def check_cache(self, org_id: str, prompt: str) -> Optional[str]:
        key = self._get_cache_key(org_id, prompt)
        if key in self._cache:
            resp, exp = self._cache[key]
            if time.time() < exp:
                logger.info(f"[LLMRouter] Prompt cache HIT for tenant '{org_id}'")
                return resp
            else:
                del self._cache[key]
        return None

    def store_cache(self, org_id: str, prompt: str, response: str, ttl_seconds: float = 300.0):
        key = self._get_cache_key(org_id, prompt)
        self._cache[key] = (response, time.time() + ttl_seconds)

    def get_degraded_response(self, prompt: str, reason: str = "HIGH_SYSTEM_LOAD") -> Dict[str, Any]:
        """
        Deterministic degraded fallback.
        Strict invariant: NEVER invents availability, prices, or room numbers.
        NEVER takes mutating action.
        """
        logger.warning(f"[LLMRouter] Falling back to deterministic degraded mode. Reason: {reason}")
        return {
            "content": (
                "Our AI concierge is currently operating in low-capacity maintenance mode. "
                "For immediate booking questions, room amenities, or urgent assistance, "
                "please contact our front desk team directly."
            ),
            "provider": "deterministic_degraded_fallback",
            "is_degraded": True,
            "degraded_reason": reason,
            "tool_calls": []
        }

    async def generate_response(
        self,
        org_id: str,
        prompt: str,
        primary_callable: Optional[Callable[[], Awaitable[str]]] = None,
        secondary_callable: Optional[Callable[[], Awaitable[str]]] = None,
        estimated_cost_usd: float = 0.002
    ) -> Dict[str, Any]:
        # 1. Enforce per-tenant spend caps
        current_spend = self._tenant_spend.get(org_id, 0.0)
        cap = self._tenant_spend_caps.get(org_id, float("inf"))
        if current_spend + estimated_cost_usd > cap:
            logger.warning(f"[LLMRouter] Spend cap exceeded for tenant '{org_id}' (${current_spend:.4f} >= ${cap:.4f})")
            return self.get_degraded_response(prompt, reason="TENANT_SPEND_CAP_EXCEEDED")

        # 2. Check prompt cache
        cached = self.check_cache(org_id, prompt)
        if cached:
            return {
                "content": cached,
                "provider": "cache",
                "is_cached": True,
                "is_degraded": False
            }

        # 3. Try Primary Provider (e.g. OpenAI)
        if primary_callable:
            try:
                res = await self.primary_breaker.call(primary_callable)
                self.record_spend(org_id, estimated_cost_usd)
                self.store_cache(org_id, prompt, res)
                return {
                    "content": res,
                    "provider": "primary",
                    "is_cached": False,
                    "is_degraded": False
                }
            except Exception as pe:
                logger.warning(f"[LLMRouter] Primary provider failed: {pe}. Failing over to secondary.")

        # 4. Failover to Secondary Provider (e.g. Anthropic)
        if secondary_callable:
            try:
                res = await self.secondary_breaker.call(secondary_callable)
                self.record_spend(org_id, estimated_cost_usd)
                self.store_cache(org_id, prompt, res)
                return {
                    "content": res,
                    "provider": "secondary",
                    "is_cached": False,
                    "is_degraded": False
                }
            except Exception as se:
                logger.warning(f"[LLMRouter] Secondary provider failed: {se}. Entering degraded mode.")

        # 5. Outage across both providers: Degraded Mode
        return self.get_degraded_response(prompt, reason="ALL_PROVIDERS_DOWN")

llm_router = LLMResilienceRouter()
