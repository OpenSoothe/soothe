"""Per-domain token bucket rate limiter for HTTP requests.

This module provides domain-aware rate limiting using the token bucket algorithm,
with support for burst capacity, concurrent request limiting, and adaptive throttling.

IG-432: Server-Polite Concurrency Control for Tacitus
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """Rate limit configuration for a domain.

    Args:
        rps: Requests per second (sustained rate).
        burst: Maximum burst capacity (bucket size).
        concurrent: Maximum concurrent requests allowed.
    """

    rps: float = 1.0
    burst: int = 3
    concurrent: int = 5

    @property
    def interval(self) -> float:
        """Return interval between requests in seconds."""
        return 1.0 / self.rps if self.rps > 0 else float("inf")


class RateLimitConfig:
    """Configuration for domain-specific rate limits.

    Provides default rate limits for common domains and allows
    customization per domain.
    """

    # Default rate limits per domain (requests per second)
    _DEFAULT_LIMITS: dict[str, RateLimit] = {
        # Search APIs
        "tavily": RateLimit(rps=1.0, burst=3, concurrent=5),
        "duckduckgo": RateLimit(rps=2.0, burst=5, concurrent=10),
        "brave": RateLimit(rps=1.0, burst=2, concurrent=3),
        # Academic APIs
        "deepxiv": RateLimit(rps=2.0, burst=5, concurrent=8),
        "arxiv.org": RateLimit(rps=1.0, burst=3, concurrent=5),
        # General web crawling (conservative)
        "default": RateLimit(rps=0.5, burst=2, concurrent=3),
    }

    def __init__(self, custom_limits: dict[str, RateLimit] | None = None) -> None:
        """Initialize with default limits and apply custom overrides.

        Args:
            custom_limits: Optional dictionary of custom rate limits.
        """
        self.limits = self._DEFAULT_LIMITS.copy()
        if custom_limits:
            self.limits.update(custom_limits)

    def get_limit(self, domain: str) -> RateLimit:
        """Get rate limit for a domain.

        Returns the configured limit for the domain, or the default
        limit if no specific configuration exists.

        Args:
            domain: Domain name to look up.

        Returns:
            RateLimit configuration for the domain.
        """
        return self.limits.get(domain, self.limits["default"])

    def update_limit(self, domain: str, limit: RateLimit) -> None:
        """Update or add a rate limit for a domain.

        Args:
            domain: Domain name to configure.
            limit: Rate limit configuration.
        """
        self.limits[domain] = limit


@dataclass
class TokenBucket:
    """Token bucket state for rate limiting.

    Implements the token bucket algorithm:
    - Tokens are added at a fixed rate (rps)
    - Tokens can accumulate up to burst capacity
    - Each request consumes 1 token
    - If no tokens available, request must wait

    Args:
        rps: Tokens added per second.
        burst: Maximum tokens that can accumulate.
    """

    rps: float
    burst: int
    _tokens: float = field(default=0.0, repr=False)
    _last_update: float = field(default_factory=time.time, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        """Initialize bucket with full tokens."""
        self._tokens = float(self.burst)

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens from the bucket.

        Blocks until the requested number of tokens are available.

        Args:
            tokens: Number of tokens to acquire (default: 1).
        """
        async with self._lock:
            while True:
                now = time.time()
                elapsed = now - self._last_update

                # Add tokens based on elapsed time
                self._tokens = min(
                    self.burst,
                    self._tokens + elapsed * self.rps,
                )
                self._last_update = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                # Calculate wait time for next token
                tokens_needed = tokens - self._tokens
                wait_seconds = tokens_needed / self.rps

                # Release lock while waiting
                await asyncio.sleep(wait_seconds)

    def get_stats(self) -> dict[str, Any]:
        """Get current bucket statistics.

        Returns:
            Dictionary with tokens available, burst capacity, and rate.
        """
        return {
            "tokens_available": round(self._tokens, 2),
            "burst_capacity": self.burst,
            "rps": self.rps,
        }


@dataclass
class DomainState:
    """Per-domain rate limiting state.

    Combines token bucket for rate limiting with semaphore for concurrency control.

    Args:
        rate_limit: Rate limit configuration.
    """

    rate_limit: RateLimit
    bucket: TokenBucket = field(init=False)
    semaphore: asyncio.Semaphore = field(init=False)
    request_count: int = field(default=0, repr=False)
    last_request_time: float | None = field(default=None, repr=False)
    adaptive_multiplier: float = field(default=1.0, repr=False)

    def __post_init__(self) -> None:
        """Initialize bucket and semaphore."""
        self.bucket = TokenBucket(
            rps=self.rate_limit.rps,
            burst=self.rate_limit.burst,
        )
        self.semaphore = asyncio.Semaphore(self.rate_limit.concurrent)

    async def acquire(self) -> None:
        """Acquire permission to make a request.

        Acquires both a token from the bucket and a slot from the semaphore.
        """
        # First acquire semaphore slot (concurrency limit)
        await self.semaphore.acquire()

        try:
            # Then acquire token from bucket (rate limit)
            await self.bucket.acquire()

            self.request_count += 1
            self.last_request_time = time.time()
        except Exception:
            # Release semaphore if token acquisition fails
            self.semaphore.release()
            raise

    def release(self) -> None:
        """Release the semaphore slot after request completes."""
        self.semaphore.release()

    def get_stats(self) -> dict[str, Any]:
        """Get domain state statistics.

        Returns:
            Dictionary with bucket stats, concurrency, and request count.
        """
        return {
            "bucket": self.bucket.get_stats(),
            "concurrent_limit": self.rate_limit.concurrent,
            "concurrent_available": self.semaphore._value,
            "request_count": self.request_count,
            "adaptive_multiplier": self.adaptive_multiplier,
        }


class DomainRateLimiter:
    """Per-domain token bucket rate limiter with connection pooling support.

    Provides rate limiting for HTTP requests on a per-domain basis using the
    token bucket algorithm. Each domain has independent rate limits, burst
    capacity, and concurrent request limits.

    Default rate limits are configured for common APIs and services. Users can
    override defaults or add custom domains via the `update_limit` method.

    Example:
        >>> limiter = DomainRateLimiter()
        >>>
        >>> # Acquire permission for a request
        >>> await limiter.acquire("tavily")
        >>> try:
        ...     # Make HTTP request
        ...     response = await http_client.get(url)
        ... finally:
        ...     limiter.release("tavily")
        >>>
        >>> # Use as async context manager
        >>> async with limiter.context("tavily"):
        ...     response = await http_client.get(url)

    IG-432: Server-Polite Concurrency Control
    """

    # Default rate limits per domain (requests per second)
    DEFAULT_LIMITS: dict[str, RateLimit] = {
        # Search APIs
        "tavily": RateLimit(rps=1.0, burst=3, concurrent=5),
        "duckduckgo": RateLimit(rps=2.0, burst=5, concurrent=10),
        "brave": RateLimit(rps=1.0, burst=2, concurrent=3),
        "wizsearch": RateLimit(rps=2.0, burst=5, concurrent=8),
        # Academic APIs
        "deepxiv": RateLimit(rps=2.0, burst=5, concurrent=8),
        "arxiv.org": RateLimit(rps=1.0, burst=3, concurrent=5),
        "biorxiv": RateLimit(rps=1.0, burst=3, concurrent=5),
        "medrxiv": RateLimit(rps=1.0, burst=3, concurrent=5),
        # Static hosting (GitHub Pages, etc.)
        "github.io": RateLimit(rps=0.5, burst=2, concurrent=3),
        # General web crawling (conservative)
        "default": RateLimit(rps=0.5, burst=2, concurrent=3),
    }

    @staticmethod
    def domain_from_url(url: str) -> str:
        """Extract domain from a URL.

        Handles various URL formats and returns the domain portion.

        Args:
            url: URL string (e.g., "https://api.tavily.com/v1/search")

        Returns:
            Domain name (e.g., "api.tavily.com")

        Example:
            >>> DomainRateLimiter.domain_from_url("https://api.tavily.com/v1/search")
            'api.tavily.com'
            >>> DomainRateLimiter.domain_from_url("http://arxiv.org/abs/1234")
            'arxiv.org'
        """
        return _domain_from_url_impl(url)

    def __init__(
        self,
        default_limits: dict[str, RateLimit] | RateLimitConfig | None = None,
        global_multiplier: float = 1.0,
        enable_adaptive: bool = True,
    ) -> None:
        """Initialize domain rate limiter.

        Args:
            default_limits: Optional dictionary of domain to RateLimit mappings,
                or a RateLimitConfig object. If not provided, uses DEFAULT_LIMITS.
            global_multiplier: Multiplier applied to all rate limits.
                Use 0.5 to halve rates, 2.0 to double them.
            enable_adaptive: Whether to enable adaptive throttling based on
                429/503 responses.
        """
        if isinstance(default_limits, RateLimitConfig):
            self._limits = default_limits.limits
        else:
            self._limits = default_limits or self.DEFAULT_LIMITS.copy()
        self._global_multiplier = max(0.1, global_multiplier)
        self._enable_adaptive = enable_adaptive

        # Domain state cache
        self._domains: dict[str, DomainState] = {}
        self._lock = asyncio.Lock()

        # Adaptive throttling state
        self._adaptive_multipliers: dict[str, float] = {}
        self._consecutive_errors: dict[str, int] = {}

        logger.debug(
            "DomainRateLimiter initialized: %d domains, multiplier=%.1f, adaptive=%s",
            len(self._limits),
            self._global_multiplier,
            enable_adaptive,
        )

    def _get_effective_limit(self, domain: str) -> RateLimit:
        """Get effective rate limit for a domain.

        Applies global multiplier and adaptive adjustments.

        Args:
            domain: Domain name.

        Returns:
            RateLimit with adjusted values.
        """
        # Find matching limit (exact match or default)
        limit = self._limits.get(domain)
        if limit is None:
            # Try suffix matching for subdomains
            for key in self._limits:
                if domain.endswith(key) and key != "default":
                    limit = self._limits[key]
                    break

        if limit is None:
            limit = self._limits.get("default", RateLimit(rps=0.5, burst=2, concurrent=3))

        # Apply adaptive multiplier
        adaptive = self._adaptive_multipliers.get(domain, 1.0)
        effective_rps = limit.rps * self._global_multiplier * adaptive

        return RateLimit(
            rps=max(0.1, effective_rps),  # Minimum 0.1 RPS
            burst=max(1, int(limit.burst * self._global_multiplier)),
            concurrent=max(1, int(limit.concurrent * self._global_multiplier)),
        )

    async def _get_domain_state(self, domain: str) -> DomainState:
        """Get or create domain state.

        Args:
            domain: Domain name.

        Returns:
            DomainState for the domain.
        """
        async with self._lock:
            if domain not in self._domains:
                limit = self._get_effective_limit(domain)
                self._domains[domain] = DomainState(rate_limit=limit)
                logger.debug(
                    "Created domain state for '%s': rps=%.1f, burst=%d, concurrent=%d",
                    domain,
                    limit.rps,
                    limit.burst,
                    limit.concurrent,
                )
            return self._domains[domain]

    def acquire(self, domain: str) -> DomainRateLimiterContext:
        """Acquire permission to make a request to the domain.

        Returns an async context manager that automatically releases on exit.

        Usage:
            async with limiter.acquire("tavily") as ctx:
                response = await http_client.get(url)

        Args:
            domain: Target domain name.

        Returns:
            Async context manager with domain attribute.
        """
        return DomainRateLimiterContext(self, domain)

    async def _do_acquire(self, domain: str) -> None:
        """Internal method to acquire permission (used by context manager).

        Args:
            domain: Target domain name.
        """
        state = await self._get_domain_state(domain)
        await state.acquire()

    async def release(self, domain: str) -> None:
        """Release the request slot for the domain.

        Must be called after request completes (success or failure).

        Args:
            domain: Target domain name.
        """
        state = self._domains.get(domain)
        if state:
            state.release()

    def context(self, domain: str) -> DomainRateLimiterContext:
        """Create async context manager for the domain.

        Usage:
            async with limiter.context("tavily"):
                response = await http_client.get(url)

        Args:
            domain: Target domain name.

        Returns:
            Async context manager that acquires/releases automatically.
        """
        return DomainRateLimiterContext(self, domain)

    def update_limit(self, domain: str, rps: float, burst: int, concurrent: int) -> None:
        """Update rate limit for a domain.

        Creates new limit or overrides existing. Affects new requests only.

        Args:
            domain: Domain name to update.
            rps: Requests per second.
            burst: Burst capacity.
            concurrent: Max concurrent requests.
        """
        self._limits[domain] = RateLimit(rps=rps, burst=burst, concurrent=concurrent)

        # Remove cached state to force recreation with new limits
        if domain in self._domains:
            del self._domains[domain]

        logger.info(
            "Updated rate limit for '%s': rps=%.1f, burst=%d, concurrent=%d",
            domain,
            rps,
            burst,
            concurrent,
        )

    def record_success(self, domain: str) -> None:
        """Record successful request for adaptive throttling.

        Resets consecutive error count and may increase rate.

        Args:
            domain: Target domain name.
        """
        if not self._enable_adaptive:
            return

        if domain in self._consecutive_errors:
            del self._consecutive_errors[domain]

        # Gradually restore adaptive multiplier
        current = self._adaptive_multipliers.get(domain, 1.0)
        if current < 1.0:
            self._adaptive_multipliers[domain] = min(1.0, current * 1.1)

    def record_rate_limit_hit(self, domain: str, retry_after: float | None = None) -> None:
        """Record rate limit error (429) for adaptive throttling.

        Reduces rate for the domain to prevent further rate limiting.

        Args:
            domain: Target domain name.
            retry_after: Optional retry-after header value in seconds.
        """
        if not self._enable_adaptive:
            return

        self._consecutive_errors[domain] = self._consecutive_errors.get(domain, 0) + 1

        # Reduce rate based on consecutive errors
        current = self._adaptive_multipliers.get(domain, 1.0)
        new_multiplier = max(0.1, current * 0.5)  # Halve the rate
        self._adaptive_multipliers[domain] = new_multiplier

        logger.warning(
            "Rate limit hit for '%s', reducing rate to %.0f%% (consecutive_errors=%d)",
            domain,
            new_multiplier * 100,
            self._consecutive_errors[domain],
        )

        # Remove cached state to apply new limits
        if domain in self._domains:
            del self._domains[domain]

    def record_server_error(self, domain: str) -> None:
        """Record server error (503) for adaptive throttling.

        Args:
            domain: Target domain name.
        """
        if not self._enable_adaptive:
            return

        self._consecutive_errors[domain] = self._consecutive_errors.get(domain, 0) + 1

        # Reduce rate for server errors
        current = self._adaptive_multipliers.get(domain, 1.0)
        new_multiplier = max(0.5, current * 0.8)
        self._adaptive_multipliers[domain] = new_multiplier

    def get_stats(self, domain: str | None = None) -> dict[str, Any]:
        """Get rate limiter statistics.

        Args:
            domain: Optional domain name to get stats for. If not provided,
                returns global statistics.

        Returns:
            Dictionary with statistics. For a specific domain, includes:
            - tokens_available: Current tokens in bucket
            - burst: Burst capacity
            - rps: Rate per second
            - concurrent_limit: Max concurrent requests
            - concurrent_available: Currently available slots
            - requests_in_progress: Number of active requests
            - request_count: Total requests made
            - adaptive_multiplier: Current adaptive multiplier

            For global stats (no domain), includes all domains and settings.
        """
        if domain is not None:
            state = self._domains.get(domain)
            if state is None:
                # Return configured limits for domains that haven't been accessed
                limit = self._get_effective_limit(domain)
                return {
                    "tokens_available": limit.burst,
                    "burst": limit.burst,
                    "rps": limit.rps,
                    "concurrent_limit": limit.concurrent,
                    "concurrent_available": limit.concurrent,
                    "requests_in_progress": 0,
                    "request_count": 0,
                    "adaptive_multiplier": self._adaptive_multipliers.get(domain, 1.0),
                }

            bucket_stats = state.bucket.get_stats()
            return {
                "tokens_available": bucket_stats["tokens_available"],
                "burst": bucket_stats["burst_capacity"],
                "rps": bucket_stats["rps"],
                "concurrent_limit": state.rate_limit.concurrent,
                "concurrent_available": state.semaphore._value,
                "requests_in_progress": state.rate_limit.concurrent - state.semaphore._value,
                "request_count": state.request_count,
                "adaptive_multiplier": state.adaptive_multiplier,
            }

        # Global stats
        domain_stats = {}
        for d, state in self._domains.items():
            domain_stats[d] = state.get_stats()

        return {
            "global_multiplier": self._global_multiplier,
            "adaptive_enabled": self._enable_adaptive,
            "configured_domains": list(self._limits.keys()),
            "active_domains": list(self._domains.keys()),
            "domains": domain_stats,
            "adaptive_multipliers": self._adaptive_multipliers.copy(),
            "consecutive_errors": self._consecutive_errors.copy(),
        }

    def get_wait_time(self, domain: str) -> float:
        """Calculate estimated wait time for next token.

        Args:
            domain: Domain name to check.

        Returns:
            Estimated seconds to wait for next token (0 if available).
        """
        state = self._domains.get(domain)
        if state is None:
            return 0.0

        bucket = state.bucket
        now = time.time()
        elapsed = now - bucket._last_update
        current_tokens = min(
            bucket.burst,
            bucket._tokens + elapsed * bucket.rps,
        )

        if current_tokens >= 1:
            return 0.0

        tokens_needed = 1 - current_tokens
        return tokens_needed / bucket.rps

    def get_global_stats(self) -> dict[str, Any]:
        """Get global statistics across all domains.

        Returns:
            Dictionary with total domains and requests in progress.
        """
        total_requests = 0
        for state in self._domains.values():
            total_requests += state.rate_limit.concurrent - state.semaphore._value

        return {
            "total_domains": len(self._domains),
            "total_requests_in_progress": total_requests,
            "global_multiplier": self._global_multiplier,
            "adaptive_enabled": self._enable_adaptive,
        }

    async def close(self) -> None:
        """Clean up resources.

        Clears all domain states and resets adaptive throttling.
        """
        async with self._lock:
            self._domains.clear()
            self._adaptive_multipliers.clear()
            self._consecutive_errors.clear()

        logger.debug("DomainRateLimiter closed")


class DomainRateLimiterContext:
    """Async context manager for domain rate limiting.

    Automatically acquires on enter and releases on exit.
    Can also be awaited directly for simple acquisition.

    Example:
        # As context manager
        async with limiter.acquire("tavily") as ctx:
            response = await http_client.get(url)

        # Or await directly (must call release separately)
        await limiter.acquire("tavily")
        # ... do work ...
        await limiter.release("tavily")
    """

    def __init__(self, limiter: DomainRateLimiter, domain: str) -> None:
        """Initialize context manager.

        Args:
            limiter: DomainRateLimiter instance.
            domain: Target domain name.
        """
        self._limiter = limiter
        self._domain = domain
        self._acquired = False

    @property
    def domain(self) -> str:
        """Return the domain being rate limited."""
        return self._domain

    def __await__(self) -> Generator[Any, None, DomainRateLimiterContext]:
        """Allow awaiting the context directly for simple acquisition."""
        return self._do_acquire().__await__()

    async def _do_acquire(self) -> DomainRateLimiterContext:
        """Internal acquire method."""
        await self._limiter._do_acquire(self._domain)
        self._acquired = True
        return self

    async def __aenter__(self) -> DomainRateLimiterContext:
        """Acquire rate limit on context enter."""
        await self._do_acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Release rate limit on context exit."""
        if self._acquired:
            await self._limiter.release(self._domain)
            self._acquired = False


# Global instance for convenience
_default_limiter: DomainRateLimiter | None = None


def get_default_limiter() -> DomainRateLimiter:
    """Get or create the default global rate limiter.

    Returns:
        Global DomainRateLimiter instance.
    """
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = DomainRateLimiter()
    return _default_limiter


def set_default_limiter(limiter: DomainRateLimiter | None) -> None:
    """Set or clear the global default rate limiter.

    Args:
        limiter: DomainRateLimiter instance or None to clear.
    """
    global _default_limiter
    _default_limiter = limiter


def _domain_from_url_impl(url: str) -> str:
    """Extract domain from a URL (implementation).

    Maps URLs to configured domain names for rate limiting.

    Args:
        url: URL string (e.g., "https://api.tavily.com/v1/search")

    Returns:
        Domain name matching configured rate limits (e.g., "tavily")
    """
    # Remove protocol prefix
    url = url.removeprefix("https://").removeprefix("http://")

    # Remove path and query
    if "/" in url:
        url = url.split("/")[0]

    # Remove port if present
    if ":" in url:
        url = url.split(":")[0]

    domain = url.lower()

    # Map to configured domain names
    domain_mappings = {
        "tavily": ["api.tavily.com", "tavily.com"],
        "duckduckgo": ["duckduckgo.com", "html.duckduckgo.com"],
        "brave": ["api.brave.com", "brave.com", "search.brave.com"],
        "deepxiv": ["deepxiv.example.com", "deepxiv.com", "api.deepxiv.com"],
        "arxiv.org": ["arxiv.org", "export.arxiv.org"],
        "biorxiv": ["biorxiv.org"],
        "medrxiv": ["medrxiv.org"],
        "github.io": ["github.io", "*.github.io"],
    }

    for mapped_domain, patterns in domain_mappings.items():
        if domain in patterns:
            return mapped_domain
        # Check suffix match for subdomains
        for pattern in patterns:
            if pattern.startswith("*."):
                suffix = pattern[2:]
                if domain.endswith(suffix):
                    return mapped_domain
            elif domain.endswith(f".{pattern}"):
                return mapped_domain

    # Return the full domain if no mapping found
    return domain


def domain_from_url(url: str) -> str:
    """Extract domain from a URL.

    Handles various URL formats and returns the domain portion.

    Args:
        url: URL string (e.g., "https://api.tavily.com/v1/search")

    Returns:
        Domain name (e.g., "api.tavily.com")

    Example:
        >>> domain_from_url("https://api.tavily.com/v1/search")
        'api.tavily.com'
        >>> domain_from_url("http://arxiv.org/abs/1234")
        'arxiv.org'
    """
    # Remove protocol prefix
    url = url.removeprefix("https://").removeprefix("http://")

    # Remove path and query
    if "/" in url:
        url = url.split("/")[0]

    # Remove port if present
    if ":" in url:
        url = url.split(":")[0]

    return url.lower()
