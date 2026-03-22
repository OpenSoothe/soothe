"""API rate limiting for multi-threaded execution."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator


class APIRateLimiter:
    """Rate limiter for API calls across all threads."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 90000,
    ) -> None:
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum API requests per minute
            tokens_per_minute: Maximum tokens per minute
        """
        self._rpm_limit = requests_per_minute
        self._tpm_limit = tokens_per_minute
        # Semaphore for request limiting (simplified, not token-aware)
        self._request_semaphore = asyncio.Semaphore(requests_per_minute // 60)

    @asynccontextmanager
    async def acquire(self, estimated_tokens: int = 1000) -> AsyncGenerator[None, None]:
        """Acquire rate limit permit.

        Args:
            estimated_tokens: Estimated tokens for this request (not used in simplified version)

        Yields:
            None
        """
        async with self._request_semaphore:
            yield
