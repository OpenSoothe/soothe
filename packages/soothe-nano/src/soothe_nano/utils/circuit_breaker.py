"""Circuit breaker pattern for fail-fast behavior.

The circuit breaker has three states:
- CLOSED: Normal operation, requests pass through
- OPEN: Fail-fast mode, requests are rejected immediately
- HALF_OPEN: Testing if the service has recovered

State transitions:
- CLOSED -> OPEN: When failure threshold is reached
- OPEN -> HALF_OPEN: After timeout period expires
- HALF_OPEN -> CLOSED: If test request succeeds
- HALF_OPEN -> OPEN: If test request fails
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from enum import Enum, auto
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = auto()  # Normal operation
    OPEN = auto()  # Fail-fast mode
    HALF_OPEN = auto()  # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open (fail-fast)."""

    def __init__(self, message: str = "Circuit breaker is OPEN - failing fast"):
        super().__init__(message)


class CircuitBreaker:
    """Circuit breaker for fail-fast behavior.

    Prevents cascading failures by rejecting requests when a service
    is known to be failing, allowing it time to recover.

    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before trying again (half-open)
        success_threshold: Consecutive successes needed to close circuit
        name: Optional name for logging
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3,
        name: str | None = None,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.name = name or "CircuitBreaker"

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None

        # Thread safety
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        """Current state of the circuit breaker."""
        with self._lock:
            return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (fail-fast mode)."""
        with self._lock:
            self._update_state()
            return self._state == CircuitBreakerState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        with self._lock:
            self._update_state()
            return self._state == CircuitBreakerState.CLOSED

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing)."""
        with self._lock:
            self._update_state()
            return self._state == CircuitBreakerState.HALF_OPEN

    def _update_state(self) -> None:
        """Update state based on timeout (OPEN -> HALF_OPEN)."""
        if self._state == CircuitBreakerState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    logger.info("[%s] Circuit transitioning OPEN -> HALF_OPEN", self.name)

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info(
                        "[%s] Circuit closing: %d consecutive successes",
                        self.name,
                        self._success_count,
                    )
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitBreakerState.HALF_OPEN:
                logger.warning("[%s] Circuit opening: failure during HALF_OPEN", self.name)
                self._state = CircuitBreakerState.OPEN
            elif (
                self._state == CircuitBreakerState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                logger.warning(
                    "[%s] Circuit opening: %d failures reached threshold",
                    self.name,
                    self._failure_count,
                )
                self._state = CircuitBreakerState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            logger.info("[%s] Circuit manually reset to CLOSED", self.name)
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap a function with circuit breaker protection.

        Usage:
            breaker = CircuitBreaker(failure_threshold=3)

            @breaker
            def my_function():
                ...
        """

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return self.call(func, *args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            return await self.call_async(func, *args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a function with circuit breaker protection (sync).

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception from the wrapped function
        """
        with self._lock:
            self._update_state()
            if self._state == CircuitBreakerState.OPEN:
                raise CircuitBreakerOpenError(
                    f"[{self.name}] Circuit breaker is OPEN - failing fast"
                )

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    async def call_async(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a function with circuit breaker protection (async).

        Args:
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception from the wrapped function
        """
        async with self._async_lock:
            with self._lock:
                self._update_state()
                if self._state == CircuitBreakerState.OPEN:
                    raise CircuitBreakerOpenError(
                        f"[{self.name}] Circuit breaker is OPEN - failing fast"
                    )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def get_stats(self) -> dict[str, Any]:
        """Get current circuit breaker statistics."""
        with self._lock:
            self._update_state()
            return {
                "name": self.name,
                "state": self._state.name,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "success_threshold": self.success_threshold,
                "recovery_timeout": self.recovery_timeout,
                "last_failure_time": self._last_failure_time,
                "time_since_last_failure": (
                    time.monotonic() - self._last_failure_time if self._last_failure_time else None
                ),
            }


def with_circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    success_threshold: int = 3,
    name: str | None = None,
) -> Callable[[Callable], Callable]:
    """Decorator factory for circuit breaker protection.

    Creates a new circuit breaker instance for the decorated function.

    Args:
        failure_threshold: Failures before opening circuit
        recovery_timeout: Seconds before trying again
        success_threshold: Successes needed to close
        name: Optional circuit breaker name

    Usage:
        @with_circuit_breaker(failure_threshold=3, recovery_timeout=30)
        async def fetch_data():
            ...
    """
    breaker = CircuitBreaker(
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        success_threshold=success_threshold,
        name=name,
    )
    return breaker
