import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, Callable, Awaitable
from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.resilience.circuit_breaker")

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str, recovery_time_left: float):
        self.name = name
        self.recovery_time_left = recovery_time_left
        super().__init__(f"Circuit breaker '{name}' is OPEN. Requests blocked for {recovery_time_left:.1f}s.")

class CircuitBreaker:
    """
    Production circuit breaker with distributed state in Redis across replicas,
    sliding failure count, bulkhead concurrency limit, and automatic recovery testing in HALF_OPEN state.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
        call_timeout: float = 10.0,
        max_concurrent_calls: int = 50
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.call_timeout = call_timeout
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.consecutive_successes = 0
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._lock = asyncio.Lock()

    async def _sync_from_redis(self):
        try:
            client = await get_redis_client()
            pipe = client.pipeline()
            pipe.get(f"hac:cb:{self.name}:state")
            pipe.get(f"hac:cb:{self.name}:failures")
            pipe.get(f"hac:cb:{self.name}:last_failure")
            pipe.get(f"hac:cb:{self.name}:successes")
            res = await pipe.execute()
            if res[0]:
                self.state = CircuitState(res[0])
            if res[1] is not None:
                self.consecutive_failures = int(res[1])
            if res[2] is not None:
                self.last_failure_time = float(res[2])
            if res[3] is not None:
                self.consecutive_successes = int(res[3])
        except Exception as e:
            logger.debug(f"[CircuitBreaker:{self.name}] Redis sync fallback to local state: {e}")

    async def _sync_to_redis(self):
        try:
            client = await get_redis_client()
            pipe = client.pipeline()
            pipe.set(f"hac:cb:{self.name}:state", self.state.value)
            pipe.set(f"hac:cb:{self.name}:failures", str(self.consecutive_failures))
            pipe.set(f"hac:cb:{self.name}:last_failure", str(self.last_failure_time))
            pipe.set(f"hac:cb:{self.name}:successes", str(self.consecutive_successes))
            await pipe.execute()
        except Exception as e:
            logger.debug(f"[CircuitBreaker:{self.name}] Redis sync write error: {e}")

    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        now = time.time()

        async with self._lock:
            await self._sync_from_redis()
            # Check if breaker should transition from OPEN to HALF_OPEN
            if self.state == CircuitState.OPEN:
                elapsed = now - self.last_failure_time
                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.consecutive_successes = 0
                    await self._sync_to_redis()
                    logger.info(f"[CircuitBreaker:{self.name}] Transitioned to HALF_OPEN (probing health)")
                else:
                    raise CircuitBreakerOpenError(self.name, self.recovery_timeout - elapsed)

        # Acquire bulkhead semaphore
        async with self._semaphore:
            try:
                # Enforce outbound call timeout
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.call_timeout)
                await self._on_success()
                return result
            except asyncio.TimeoutError as te:
                await self._on_failure()
                raise TimeoutError(f"[CircuitBreaker:{self.name}] Call timed out after {self.call_timeout}s") from te
            except Exception as e:
                await self._on_failure()
                raise e

    async def _on_success(self):
        async with self._lock:
            await self._sync_from_redis()
            if self.state == CircuitState.HALF_OPEN:
                self.consecutive_successes += 1
                if self.consecutive_successes >= 2:
                    self.state = CircuitState.CLOSED
                    self.consecutive_failures = 0
                    logger.info(f"[CircuitBreaker:{self.name}] Recovered to CLOSED state.")
            elif self.state == CircuitState.CLOSED:
                self.consecutive_failures = 0
            await self._sync_to_redis()

    async def _on_failure(self):
        async with self._lock:
            await self._sync_from_redis()
            self.last_failure_time = time.time()
            self.consecutive_failures += 1
            if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker:{self.name}] Tripped to OPEN state! "
                    f"Failures: {self.consecutive_failures}/{self.failure_threshold}"
                )
            await self._sync_to_redis()

    def reset(self):
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.consecutive_successes = 0
        try:
            from services.common.redis_service import get_redis_client_sync
            r = get_redis_client_sync()
            r.delete(f"hac:cb:{self.name}:state", f"hac:cb:{self.name}:failures", f"hac:cb:{self.name}:last_failure", f"hac:cb:{self.name}:successes")
        except Exception:
            pass


# Registry of circuit breakers for outbound integrations
_CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {}

def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 10.0,
    call_timeout: float = 10.0,
    max_concurrent_calls: int = 50
) -> CircuitBreaker:
    if name not in _CIRCUIT_BREAKERS:
        _CIRCUIT_BREAKERS[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            call_timeout=call_timeout,
            max_concurrent_calls=max_concurrent_calls
        )
    return _CIRCUIT_BREAKERS[name]
