"""Rate limiting for filesystem operations.

This module provides rate limiting capabilities to prevent abuse of filesystem
operations, using token bucket algorithm for smooth rate control.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class RateLimitStrategy(Enum):
    """Rate limiting strategies."""

    TOKEN_BUCKET = auto()
    FIXED_WINDOW = auto()
    SLIDING_WINDOW = auto()


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        requests_per_second: Maximum requests allowed per second.
        burst_size: Maximum burst of requests allowed.
        cooldown_seconds: Seconds to wait after rate limit hit.
        strategy: Rate limiting algorithm to use.
        per_operation: Whether to track limits per operation type.
        per_path: Whether to track limits per path.
        per_user: Whether to track limits per user/session.
    """

    requests_per_second: float = 10.0
    burst_size: int = 20
    cooldown_seconds: float = 1.0
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    per_operation: bool = True
    per_path: bool = False
    per_user: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "requests_per_second": self.requests_per_second,
            "burst_size": self.burst_size,
            "cooldown_seconds": self.cooldown_seconds,
            "strategy": self.strategy.name,
            "per_operation": self.per_operation,
            "per_path": self.per_path,
            "per_user": self.per_user,
        }


@dataclass
class RateLimitStatus:
    """Current rate limit status for a key."""

    key: str
    tokens: float
    last_request: float
    request_count: int
    limited_until: float | None = None

    @property
    def is_limited(self) -> bool:
        """Check if currently rate limited."""
        if self.limited_until is None:
            return False
        return time.monotonic() < self.limited_until

    @property
    def retry_after(self) -> float:
        """Seconds until request can be retried."""
        if self.limited_until is None:
            return 0.0
        remaining = self.limited_until - time.monotonic()
        return max(0.0, remaining)


class RateLimiter:
    """Token bucket rate limiter for filesystem operations.

    This implementation uses the token bucket algorithm for smooth rate control,
    with support for per-operation, per-path, and per-user rate limiting.

    Example:
        >>> limiter = RateLimiter(RateLimitConfig(requests_per_second=5))
        >>> await limiter.acquire("read", path="/file.txt")
        >>> # Perform operation
        >>> limiter.release("read", path="/file.txt")
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        """Initialize rate limiter.

        Args:
            config: Rate limiting configuration. Uses defaults if None.
        """
        self._config = config or RateLimitConfig()
        self._buckets: dict[str, RateLimitStatus] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._shutdown = False

    async def start(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop background cleanup task."""
        self._shutdown = True
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    def _make_key(
        self,
        operation: str,
        path: str | None = None,
        user: str | None = None,
    ) -> str:
        """Create a rate limit key based on configuration."""
        parts = [operation]
        if self._config.per_path and path:
            parts.append(f"path:{path}")
        if self._config.per_user and user:
            parts.append(f"user:{user}")
        return "|".join(parts)

    def _get_or_create_bucket(self, key: str) -> RateLimitStatus:
        """Get existing bucket or create new one."""
        now = time.monotonic()
        if key not in self._buckets:
            self._buckets[key] = RateLimitStatus(
                key=key,
                tokens=self._config.burst_size,
                last_request=now,
                request_count=0,
            )
        return self._buckets[key]

    def _refill_tokens(self, bucket: RateLimitStatus) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - bucket.last_request
        tokens_to_add = elapsed * self._config.requests_per_second
        bucket.tokens = min(
            self._config.burst_size,
            bucket.tokens + tokens_to_add
        )
        bucket.last_request = now

    async def acquire(
        self,
        operation: str,
        *,
        path: str | None = None,
        user: str | None = None,
        timeout: float | None = None,
    ) -> RateLimitStatus:
        """Acquire permission to perform an operation.

        Args:
            operation: Operation type (e.g., 'read', 'write', 'delete').
            path: Optional path for per-path limiting.
            user: Optional user identifier for per-user limiting.
            timeout: Maximum seconds to wait for acquisition.

        Returns:
            RateLimitStatus for the acquired key.

        Raises:
            RateLimitExceeded: If rate limit is exceeded and timeout expires.
        """
        key = self._make_key(operation, path, user)
        deadline = time.monotonic() + timeout if timeout else None

        async with self._lock:
            bucket = self._get_or_create_bucket(key)

            while True:
                # Check if currently limited
                if bucket.is_limited:
                    if deadline and time.monotonic() >= deadline:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded for {key}",
                            retry_after=bucket.retry_after,
                            key=key,
                        )
                    wait_time = bucket.retry_after
                    if deadline and time.monotonic() + wait_time > deadline:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded for {key}",
                            retry_after=bucket.retry_after,
                            key=key,
                        )
                    await asyncio.sleep(wait_time)
                    continue

                # Refill tokens
                self._refill_tokens(bucket)

                # Check if we can consume a token
                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    bucket.request_count += 1
                    return bucket

                # No tokens available, calculate wait time
                tokens_needed = 1 - bucket.tokens
                wait_time = tokens_needed / self._config.requests_per_second

                if deadline and time.monotonic() + wait_time > deadline:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for {key}",
                        retry_after=wait_time,
                        key=key,
                    )

                # Release lock while waiting
                await asyncio.sleep(wait_time)

                # Re-acquire and check again
                bucket = self._get_or_create_bucket(key)

    async def try_acquire(
        self,
        operation: str,
        *,
        path: str | None = None,
        user: str | None = None,
    ) -> RateLimitStatus | None:
        """Try to acquire permission without waiting.

        Args:
            operation: Operation type.
            path: Optional path for per-path limiting.
            user: Optional user identifier.

        Returns:
            RateLimitStatus if acquired, None if rate limited.
        """
        try:
            return await self.acquire(operation, path=path, user=user, timeout=0)
        except RateLimitExceeded:
            return None

    def release(
        self,
        operation: str,
        *,
        path: str | None = None,
        user: str | None = None,
    ) -> None:
        """Release a previously acquired rate limit (no-op for token bucket).

        This method exists for API consistency but token bucket doesn't
        require explicit release.

        Args:
            operation: Operation type.
            path: Optional path.
            user: Optional user identifier.
        """
        pass  # Token bucket doesn't require release

    def get_status(
        self,
        operation: str,
        *,
        path: str | None = None,
        user: str | None = None,
    ) -> RateLimitStatus:
        """Get current rate limit status without consuming tokens.

        Args:
            operation: Operation type.
            path: Optional path.
            user: Optional user identifier.

        Returns:
            Current rate limit status.
        """
        key = self._make_key(operation, path, user)
        bucket = self._get_or_create_bucket(key)
        self._refill_tokens(bucket)
        return bucket

    def get_all_statuses(self) -> dict[str, RateLimitStatus]:
        """Get all rate limit statuses.

        Returns:
            Dictionary mapping keys to their statuses.
        """
        result = {}
        for key, bucket in self._buckets.items():
            self._refill_tokens(bucket)
            result[key] = RateLimitStatus(
                key=bucket.key,
                tokens=bucket.tokens,
                last_request=bucket.last_request,
                request_count=bucket.request_count,
                limited_until=bucket.limited_until,
            )
        return result

    async def _cleanup_loop(self) -> None:
        """Background task to clean up stale buckets."""
        try:
            while not self._shutdown:
                await asyncio.sleep(60)  # Cleanup every minute
                await self._cleanup_stale_buckets()
        except asyncio.CancelledError:
            pass

    async def _cleanup_stale_buckets(self) -> None:
        """Remove buckets that haven't been used recently."""
        now = time.monotonic()
        stale_threshold = 300  # 5 minutes

        async with self._lock:
            stale_keys = [
                key for key, bucket in self._buckets.items()
                if now - bucket.last_request > stale_threshold
            ]
            for key in stale_keys:
                del self._buckets[key]

            if stale_keys:
                logger.debug(f"Cleaned up {len(stale_keys)} stale rate limit buckets")

    async def __aenter__(self) -> RateLimiter:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float,
        key: str,
    ) -> None:
        """Initialize rate limit exceeded exception.

        Args:
            message: Error message.
            retry_after: Seconds until retry is allowed.
            key: Rate limit key that was exceeded.
        """
        super().__init__(message)
        self.retry_after = retry_after
        self.key = key

    def __str__(self) -> str:
        return f"{super().__str__()} (retry after {self.retry_after:.2f}s)"


class OperationRateLimiter:
    """Decorator-style rate limiter for filesystem operations.

    This class provides a convenient way to wrap filesystem operations
    with rate limiting.

    Example:
        >>> limiter = OperationRateLimiter(RateLimitConfig())
        >>> @limiter.limit("read")
        ... async def read_file(path: str) -> str:
        ...     return await fs.read(path)
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        """Initialize operation rate limiter.

        Args:
            config: Rate limiting configuration.
        """
        self._limiter = RateLimiter(config)

    async def start(self) -> None:
        """Start the rate limiter."""
        await self._limiter.start()

    async def stop(self) -> None:
        """Stop the rate limiter."""
        await self._limiter.stop()

    def limit(
        self,
        operation: str,
        *,
        path_arg: str | None = None,
        user_arg: str | None = None,
    ) -> Callable:
        """Decorator to rate limit an operation.

        Args:
            operation: Operation type.
            path_arg: Name of argument containing path.
            user_arg: Name of argument containing user.

        Returns:
            Decorator function.
        """
        def decorator(func: Callable) -> Callable:
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                path = kwargs.get(path_arg) if path_arg else None
                user = kwargs.get(user_arg) if user_arg else None

                await self._limiter.acquire(operation, path=path, user=user)
                try:
                    return await func(*args, **kwargs)
                finally:
                    self._limiter.release(operation, path=path, user=user)

            return wrapper
        return decorator

    async def __aenter__(self) -> OperationRateLimiter:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()
