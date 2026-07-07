"""Polite HTTP client with rate limiting, circuit breaker, and connection pooling."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """Rate limit configuration for a domain."""

    rps: float = 1.0  # Requests per second
    burst: int = 3  # Maximum burst size
    concurrent: int = 5  # Maximum concurrent requests

    def __post_init__(self):
        if self.rps <= 0:
            raise ValueError("rps must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")
        if self.concurrent < 1:
            raise ValueError("concurrent must be at least 1")


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Default rate limits per domain (requests per second)
    DEFAULT_LIMITS: ClassVar[dict[str, RateLimit]] = {
        # Search APIs
        "tavily": RateLimit(rps=1.0, burst=3, concurrent=5),
        "duckduckgo": RateLimit(rps=2.0, burst=5, concurrent=10),
        "brave": RateLimit(rps=1.0, burst=2, concurrent=3),
        # Academic APIs
        "deepxiv": RateLimit(rps=2.0, burst=5, concurrent=8),
        "arxiv.org": RateLimit(rps=1.0, burst=3, concurrent=5),
        "biorxiv.org": RateLimit(rps=1.0, burst=2, concurrent=3),
        "medrxiv.org": RateLimit(rps=1.0, burst=2, concurrent=3),
        # General web crawling (conservative)
        "default": RateLimit(rps=0.5, burst=2, concurrent=3),
    }

    limits: dict[str, RateLimit] = field(default_factory=dict)
    multiplier: float = 1.0

    def get_limit(self, domain: str) -> RateLimit:
        """Get rate limit for domain, applying multiplier."""
        limit = (
            self.limits.get(domain)
            or self.DEFAULT_LIMITS.get(domain)
            or self.DEFAULT_LIMITS["default"]
        )
        if self.multiplier != 1.0:
            return RateLimit(
                rps=limit.rps * self.multiplier,
                burst=int(limit.burst * self.multiplier),
                concurrent=int(limit.concurrent * self.multiplier),
            )
        return limit


class TokenBucket:
    """Token bucket for rate limiting."""

    def __init__(self, rps: float, burst: int):
        self.rps = rps
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Acquire a token, returning wait time."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rps)
            self.last_update = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return 0.0

            # Calculate wait time for next token
            wait_time = (1.0 - self.tokens) / self.rps
            self.tokens = 0.0
            return wait_time


class DomainRateLimiter:
    """Per-domain token bucket rate limiter."""

    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self._buckets: dict[str, TokenBucket] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _get_bucket(self, domain: str) -> TokenBucket:
        """Get or create token bucket for domain."""
        if domain not in self._buckets:
            limit = self.config.get_limit(domain)
            self._buckets[domain] = TokenBucket(limit.rps, limit.burst)
        return self._buckets[domain]

    def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Get or create semaphore for domain."""
        if domain not in self._semaphores:
            limit = self.config.get_limit(domain)
            self._semaphores[domain] = asyncio.Semaphore(limit.concurrent)
        return self._semaphores[domain]

    async def acquire(self, domain: str) -> None:
        """Acquire permission to make request to domain."""
        # First acquire the semaphore (concurrency limit)
        semaphore = self._get_semaphore(domain)
        await semaphore.acquire()

        try:
            # Then wait for rate limit token
            bucket = self._get_bucket(domain)
            wait_time = await bucket.acquire()
            if wait_time > 0:
                logger.debug("Rate limiting %s: waiting %.2fs", domain, wait_time)
                await asyncio.sleep(wait_time)
        except Exception:
            # Release semaphore if token acquisition fails
            try:
                semaphore.release()
            except ValueError:
                pass  # Semaphore was already released
            raise

    def release(self, domain: str) -> None:
        """Release semaphore for domain."""
        if domain in self._semaphores:
            self._semaphores[domain].release()

    async def __aenter__(self) -> DomainRateLimiter:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class CircuitBreakerState:
    """Circuit breaker state machine."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker for failing external services."""

    def __init__(
        self,
        threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_max: int = 3,
    ):
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self.half_open_max = half_open_max
        self.failures = 0
        self.successes = 0
        self.last_failure_time: float | None = None
        self.state = CircuitBreakerState.CLOSED
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.successes = 0
                    logger.debug("Circuit breaker entering half-open state")
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is OPEN, retry after {self.reset_timeout}s"
                    )

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try reset."""
        if self.last_failure_time is None:
            return True
        return time.monotonic() - self.last_failure_time >= self.reset_timeout

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.successes += 1
                if self.successes >= self.half_open_max:
                    self.state = CircuitBreakerState.CLOSED
                    self.failures = 0
                    self.successes = 0
                    logger.info("Circuit breaker CLOSED (service recovered)")
            else:
                self.failures = max(0, self.failures - 1)

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self.failures += 1
            self.last_failure_time = time.monotonic()

            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                logger.warning("Circuit breaker OPEN (failure in half-open)")
            elif self.failures >= self.threshold:
                self.state = CircuitBreakerState.OPEN
                logger.warning("Circuit breaker OPEN (%d failures)", self.failures)

    @property
    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self.state == CircuitBreakerState.OPEN


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


class RetryableError(Exception):
    """Error that can be retried."""

    pass


class PoliteHTTPClient:
    """HTTP client with rate limiting, circuit breaker, and retry logic."""

    # HTTP status codes that trigger retry
    RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {429, 500, 502, 503, 504}

    # Exception types that trigger retry
    RETRYABLE_EXCEPTIONS: ClassVar[tuple[type, ...]] = (
        asyncio.TimeoutError,
        ConnectionError,
        OSError,
    )

    def __init__(
        self,
        rate_limiter: DomainRateLimiter | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        enable_circuit_breaker: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_sec: float = 60.0,
        circuit_breaker_half_open_max: int = 3,
    ):
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.enable_circuit_breaker = enable_circuit_breaker
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_reset_sec = circuit_breaker_reset_sec
        self.circuit_breaker_half_open_max = circuit_breaker_half_open_max
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove port if present
            if ":" in domain:
                domain = domain.split(":")[0]
            return domain if domain else "default"
        except Exception:
            return "default"

    def _get_circuit_breaker(self, domain: str) -> CircuitBreaker:
        """Get or create circuit breaker for domain."""
        if domain not in self._circuit_breakers:
            self._circuit_breakers[domain] = CircuitBreaker(
                threshold=self.circuit_breaker_threshold,
                reset_timeout=self.circuit_breaker_reset_sec,
                half_open_max=self.circuit_breaker_half_open_max,
            )
        return self._circuit_breakers[domain]

    def _is_retryable(self, exception: Exception) -> bool:
        """Check if exception is retryable."""
        if isinstance(exception, self.RETRYABLE_EXCEPTIONS):
            return True
        if hasattr(exception, "status") and exception.status in self.RETRYABLE_STATUS_CODES:
            return True
        return isinstance(exception, RetryableError)

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.base_delay * (2**attempt)
        # Use time.monotonic() for jitter to avoid asyncio event loop dependency
        jitter = delay * 0.1 * (time.monotonic() % 1 - 0.5)
        return min(delay + jitter, self.max_delay)

    async def request(
        self,
        method: str,
        url: str,
        domain: str | None = None,
        request_func: Callable | None = None,
        **kwargs,
    ) -> Any:
        """Make HTTP request with rate limiting, circuit breaker, and retry.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            domain: Optional domain override for rate limiting
            request_func: Async function to execute the request
            **kwargs: Additional arguments passed to request_func

        Returns:
            Response from request_func

        Raises:
            CircuitBreakerOpenError: If circuit breaker is open
            Exception: Last exception after retries exhausted
        """
        domain = domain or self._extract_domain(url)
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                # Acquire rate limit permission
                await self.rate_limiter.acquire(domain)

                try:
                    # Execute request with circuit breaker
                    if self.enable_circuit_breaker:
                        cb = self._get_circuit_breaker(domain)
                        result = await cb.call(
                            request_func or self._default_request, method, url, **kwargs
                        )
                    else:
                        result = await (request_func or self._default_request)(
                            method, url, **kwargs
                        )

                    return result

                finally:
                    # Always release the rate limiter
                    self.rate_limiter.release(domain)

            except Exception as e:
                last_exception = e

                # Don't retry circuit breaker errors
                if isinstance(e, CircuitBreakerOpenError):
                    raise

                # Check if error is retryable
                if not self._is_retryable(e):
                    raise

                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        "Request to %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        domain,
                        attempt + 1,
                        self.max_retries + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Request to %s failed after %d attempts: %s",
                        domain,
                        self.max_retries + 1,
                        e,
                    )
                    raise

        # Should never reach here
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected state in retry loop")

    async def _default_request(self, method: str, url: str, **kwargs) -> Any:
        """Default request implementation (placeholder).

        Subclasses should override this or provide request_func.
        """
        raise NotImplementedError("Either override _default_request or provide request_func")

    async def get(self, url: str, **kwargs) -> Any:
        """Convenience method for GET requests."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Any:
        """Convenience method for POST requests."""
        return await self.request("POST", url, **kwargs)

    async def __aenter__(self) -> PoliteHTTPClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class PoliteClientContext:
    """Context manager for using polite client with automatic cleanup."""

    def __init__(self, client: PoliteHTTPClient, domain: str):
        self.client = client
        self.domain = domain
        self._acquired = False

    async def __aenter__(self) -> PoliteClientContext:
        await self.client.rate_limiter.acquire(self.domain)
        self._acquired = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired:
            self.client.rate_limiter.release(self.domain)


# Global client instance (lazy initialization)
_global_client: PoliteHTTPClient | None = None


def get_global_polite_client(
    max_retries: int = 3,
    base_delay: float = 1.0,
    enable_circuit_breaker: bool = True,
) -> PoliteHTTPClient:
    """Get or create global polite HTTP client."""
    global _global_client
    if _global_client is None:
        _global_client = PoliteHTTPClient(
            max_retries=max_retries,
            base_delay=base_delay,
            enable_circuit_breaker=enable_circuit_breaker,
        )
    return _global_client


def reset_global_client() -> None:
    """Reset global client (useful for testing)."""
    global _global_client
    _global_client = None
