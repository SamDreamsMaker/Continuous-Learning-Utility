"""Resilience primitives: exponential backoff, circuit breaker, resilient provider wrapper.

Usage:
    provider = create_provider(...)
    resilient = ResilientProvider(provider)
    # Now use resilient instead — it retries, backs off, and circuit-breaks automatically.
"""

import logging
import random
import time
from enum import Enum

from orchestrator.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class ExponentialBackoff:
    """Exponential backoff with jitter.

    delay = min(base * 2^attempt, max_delay) + random(0, jitter)
    """

    def __init__(
        self,
        base: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.5,
    ):
        self.base = base
        self.max_delay = max_delay
        self.jitter = jitter

    def delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number (0-based)."""
        exp_delay = min(self.base * (2 ** attempt), self.max_delay)
        jitter_val = random.uniform(0, self.jitter * exp_delay)
        return exp_delay + jitter_val

    def wait(self, attempt: int):
        """Sleep for the calculated delay."""
        d = self.delay(attempt)
        logger.debug("Backoff: attempt %d, waiting %.1fs", attempt, d)
        time.sleep(d)


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker pattern.

    CLOSED → OPEN after `failure_threshold` consecutive failures.
    OPEN → HALF_OPEN after `recovery_timeout` seconds.
    HALF_OPEN → CLOSED on success, OPEN on failure.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._total_trips = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: OPEN → HALF_OPEN (testing recovery)")
        return self._state

    @property
    def allows_request(self) -> bool:
        s = self.state
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker: HALF_OPEN → CLOSED (recovered)")
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._total_trips += 1
            logger.warning("Circuit breaker: HALF_OPEN → OPEN (recovery failed)")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._total_trips += 1
            logger.warning(
                "Circuit breaker: CLOSED → OPEN after %d failures",
                self._failure_count,
            )

    @property
    def status(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_trips": self._total_trips,
        }


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejecting calls."""
    pass


class ResilientProvider(LLMProvider):
    """Wraps an LLMProvider with retry + exponential backoff + circuit breaker.

    Transparent to callers — same interface as LLMProvider.
    """

    # Errors that are worth retrying (transient)
    RETRYABLE_ERRORS = (
        ConnectionError, TimeoutError, OSError,
    )
    # Substrings in error messages that indicate transient failures
    RETRYABLE_MESSAGES = (
        "rate limit", "429", "503", "502", "500",
        "timeout", "connection", "temporarily",
    )

    def __init__(
        self,
        provider: LLMProvider,
        max_retries: int = 3,
        backoff: ExponentialBackoff | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._provider = provider
        self.max_retries = max_retries
        self.backoff = backoff or ExponentialBackoff()
        self.circuit = circuit_breaker or CircuitBreaker()

        self._total_calls = 0
        self._total_retries = 0
        self._total_failures = 0

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Chat completion with retry + circuit breaker."""
        self._total_calls += 1

        if not self.circuit.allows_request:
            raise CircuitOpenError(
                f"Circuit breaker is OPEN (state={self.circuit.state.value}). "
                f"Will retry in {self.circuit.recovery_timeout}s."
            )

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._provider.chat_completion(
                    messages=messages, tools=tools, **kwargs
                )
                self.circuit.record_success()
                return response

            except Exception as e:
                last_error = e
                if attempt < self.max_retries and self._is_retryable(e):
                    self._total_retries += 1
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying...",
                        attempt + 1, self.max_retries + 1, str(e)[:100],
                    )
                    self.backoff.wait(attempt)
                else:
                    break

        # All retries exhausted
        self._total_failures += 1
        self.circuit.record_failure()
        logger.error("LLM call failed after %d attempts: %s", self.max_retries + 1, last_error)
        raise last_error

    def test_connection(self) -> dict:
        """Test connection (no retry — just pass through)."""
        return self._provider.test_connection()

    def list_models(self) -> list[str]:
        return self._provider.list_models()

    @property
    def status(self) -> dict:
        return {
            "total_calls": self._total_calls,
            "total_retries": self._total_retries,
            "total_failures": self._total_failures,
            "circuit": self.circuit.status,
        }

    def _is_retryable(self, error: Exception) -> bool:
        """Check if the error is transient and worth retrying."""
        # Context overflow is permanent — never retry
        from orchestrator.exceptions import ContextOverflowError
        if isinstance(error, ContextOverflowError):
            return False
        if isinstance(error, self.RETRYABLE_ERRORS):
            return True
        msg = str(error).lower()
        return any(s in msg for s in self.RETRYABLE_MESSAGES)
