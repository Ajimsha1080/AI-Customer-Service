import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, Callable, Awaitable

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
    Production circuit breaker with sliding failure count, bulkhead concurrency limit,
    and automatic recovery testing in HALF_OPEN state.
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

    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        now = time.time()

        async with self._lock:
            # Check if breaker should transition from OPEN to HALF_OPEN
            if self.state == CircuitState.OPEN:
                elapsed = now - self.last_failure_time
                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.consecutive_successes = 0
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
            if self.state == CircuitState.HALF_OPEN:
                self.consecutive_successes += 1
                if self.consecutive_successes >= 2:
                    self.state = CircuitState.CLOSED
                    self.consecutive_failures = 0
                    logger.info(f"[CircuitBreaker:{self.name}] Recovered to CLOSED state.")
            elif self.state == CircuitState.CLOSED:
                self.consecutive_failures = 0

    async def _on_failure(self):
        async with self._lock:
            self.last_failure_time = time.time()
            self.consecutive_failures += 1
            if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker:{self.name}] Tripped to OPEN state! "
                    f"Failures: {self.consecutive_failures}/{self.failure_threshold}"
                )

    def reset(self):
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.consecutive_successes = 0


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
