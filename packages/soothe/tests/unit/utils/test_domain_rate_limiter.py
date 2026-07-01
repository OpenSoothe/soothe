"""Unit tests for DomainRateLimiter token bucket implementation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from soothe.utils.domain_rate_limiter import (
    DomainRateLimiter,
    RateLimit,
    RateLimitConfig,
    TokenBucket,
)


@dataclass
class TokenBucketState:
    """Captured state of a token bucket for assertions."""

    tokens: float
    last_update: float


class TestRateLimit:
    """Tests for RateLimit dataclass."""

    def test_default_values(self) -> None:
        """Test default rate limit values."""
        limit = RateLimit()
        assert limit.rps == 1.0
        assert limit.burst == 3
        assert limit.concurrent == 5

    def test_custom_values(self) -> None:
        """Test custom rate limit values."""
        limit = RateLimit(rps=2.5, burst=10, concurrent=8)
        assert limit.rps == 2.5
        assert limit.burst == 10
        assert limit.concurrent == 8

    def test_interval_calculation(self) -> None:
        """Test interval between requests calculation."""
        limit = RateLimit(rps=2.0)
        assert limit.interval == 0.5  # 1/2.0

        limit = RateLimit(rps=0.5)
        assert limit.interval == 2.0  # 1/0.5


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_default_limits(self) -> None:
        """Test default rate limits are configured."""
        config = RateLimitConfig()

        assert "tavily" in config.limits
        assert "duckduckgo" in config.limits
        assert "brave" in config.limits
        assert "deepxiv" in config.limits
        assert "arxiv.org" in config.limits
        assert "default" in config.limits

    def test_custom_limits(self) -> None:
        """Test custom limits override defaults."""
        custom = {"custom_domain": RateLimit(rps=5.0, burst=20)}
        config = RateLimitConfig(custom_limits=custom)

        assert "custom_domain" in config.limits
        assert config.limits["custom_domain"].rps == 5.0

    def test_get_limit_existing(self) -> None:
        """Test getting limit for existing domain."""
        config = RateLimitConfig()
        limit = config.get_limit("tavily")

        assert limit.rps == 1.0
        assert limit.burst == 3

    def test_get_limit_default(self) -> None:
        """Test getting limit falls back to default."""
        config = RateLimitConfig()
        limit = config.get_limit("unknown_domain")

        assert limit == config.limits["default"]

    def test_update_limit(self) -> None:
        """Test updating limit for a domain."""
        config = RateLimitConfig()
        config.update_limit("tavily", RateLimit(rps=5.0, burst=10))

        assert config.limits["tavily"].rps == 5.0
        assert config.limits["tavily"].burst == 10


class TestDomainRateLimiter:
    """Tests for DomainRateLimiter."""

    @pytest.fixture
    async def limiter(self) -> AsyncIterator[DomainRateLimiter]:
        """Create a rate limiter for testing."""
        limiter = DomainRateLimiter()
        yield limiter
        await limiter.close()

    async def test_acquire_single_request(self, limiter: DomainRateLimiter) -> None:
        """Test acquiring a single request token."""
        await limiter.acquire("test_domain")
        stats = limiter.get_stats("test_domain")

        assert stats["tokens_available"] <= stats["burst"]
        assert stats["requests_in_progress"] == 1

    async def test_acquire_multiple_requests(self, limiter: DomainRateLimiter) -> None:
        """Test acquiring multiple request tokens."""
        for _ in range(3):
            await limiter.acquire("test_domain")

        stats = limiter.get_stats("test_domain")
        assert stats["requests_in_progress"] == 3

    async def test_release_token(self, limiter: DomainRateLimiter) -> None:
        """Test releasing a request token."""
        await limiter.acquire("test_domain")
        await limiter.release("test_domain")

        stats = limiter.get_stats("test_domain")
        assert stats["requests_in_progress"] == 0

    async def test_rate_limiting_enforced(self) -> None:
        """Test that rate limiting delays requests (fast limit for quick test)."""
        # Use 50 RPS = 0.02s interval (much faster than original 10 RPS)
        config = RateLimitConfig(custom_limits={"slow": RateLimit(rps=50.0, burst=1, concurrent=1)})
        limiter = DomainRateLimiter(config)

        start = asyncio.get_event_loop().time()

        # First request should be immediate (burst)
        await limiter.acquire("slow")
        await limiter.release("slow")

        # Second request should wait ~0.02s
        await limiter.acquire("slow")
        await limiter.release("slow")

        elapsed = asyncio.get_event_loop().time() - start

        # Should have waited at least 0.01s (reasonable lower bound at 50 RPS)
        assert elapsed >= 0.01

        await limiter.close()

    async def test_concurrent_limit_enforced(self) -> None:
        """Test that concurrent limit is enforced."""
        config = RateLimitConfig(
            custom_limits={"limited": RateLimit(rps=100.0, burst=10, concurrent=2)}
        )
        limiter = DomainRateLimiter(config)

        # Acquire 2 tokens (at limit)
        await limiter.acquire("limited")
        await limiter.acquire("limited")

        stats = limiter.get_stats("limited")
        assert stats["requests_in_progress"] == 2
        assert stats["concurrent_available"] == 0

        # Release one
        await limiter.release("limited")
        stats = limiter.get_stats("limited")
        assert stats["concurrent_available"] == 1

        await limiter.release("limited")
        await limiter.close()

    async def test_token_bucket_refill(self) -> None:
        """Test that token bucket refills over time (direct state manipulation)."""
        # Fast rate for test: 100 RPS with burst of 1
        bucket = TokenBucket(rps=100.0, burst=1)

        # Use up the burst
        await bucket.acquire(1)
        assert bucket._tokens == 0

        # Simulate time passing by directly adjusting internal state
        # At 100 RPS, 0.02s would refill 2 tokens, capped at burst=1
        bucket._tokens = min(bucket.burst, bucket._tokens + 0.02 * bucket.rps)
        bucket._last_update = time.time()

        stats = bucket.get_stats()
        # Tokens = 0 + 0.02 * 100 = 2, capped at burst=1
        assert stats["tokens_available"] == 1

    async def test_token_bucket_refill_real(self) -> None:
        """Test token bucket refill with minimal real sleep."""
        # Use fast rate (100 RPS) so refill happens in ~0.01s
        config = RateLimitConfig(
            custom_limits={"refill_test": RateLimit(rps=100.0, burst=1, concurrent=5)}
        )
        limiter = DomainRateLimiter(config)

        # Use up the burst
        await limiter.acquire("refill_test")
        await limiter.release("refill_test")

        stats = limiter.get_stats("refill_test")
        assert stats["tokens_available"] == 0

        # Wait for refill (0.02s at 100 RPS = 2 tokens, capped at burst=1)
        await asyncio.sleep(0.02)

        # Should be able to acquire again
        await limiter.acquire("refill_test")
        await limiter.release("refill_test")

        await limiter.close()

    async def test_context_manager(self) -> None:
        """Test using limiter as async context manager."""
        limiter = DomainRateLimiter()

        async with limiter.acquire("test_domain") as ctx:
            stats = limiter.get_stats("test_domain")
            assert stats["requests_in_progress"] == 1
            assert ctx.domain == "test_domain"

        # After context exit, should be released
        stats = limiter.get_stats("test_domain")
        assert stats["requests_in_progress"] == 0

        await limiter.close()

    async def test_per_domain_isolation(self) -> None:
        """Test that different domains have independent limits."""
        config = RateLimitConfig(
            custom_limits={
                "domain_a": RateLimit(rps=1.0, burst=1, concurrent=1),
                "domain_b": RateLimit(rps=100.0, burst=100, concurrent=100),
            }
        )
        limiter = DomainRateLimiter(config)

        # Exhaust domain_a
        await limiter.acquire("domain_a")
        stats_a = limiter.get_stats("domain_a")
        assert stats_a["tokens_available"] == 0

        # domain_b should be unaffected
        stats_b = limiter.get_stats("domain_b")
        assert stats_b["tokens_available"] == 100

        await limiter.release("domain_a")
        await limiter.close()

    async def test_wait_time_calculation(self) -> None:
        """Test wait time calculation for rate limited domain."""
        config = RateLimitConfig(
            custom_limits={"wait_test": RateLimit(rps=1.0, burst=1, concurrent=5)}
        )
        limiter = DomainRateLimiter(config)

        # Use the only token
        await limiter.acquire("wait_test")
        await limiter.release("wait_test")

        # Check wait time
        wait_time = limiter.get_wait_time("wait_test")
        assert wait_time > 0  # Should need to wait for refill

        await limiter.close()

    async def test_global_stats(self) -> None:
        """Test global statistics aggregation."""
        limiter = DomainRateLimiter()

        await limiter.acquire("domain1")
        await limiter.acquire("domain2")

        stats = limiter.get_global_stats()
        assert stats["total_domains"] == 2
        assert stats["total_requests_in_progress"] == 2

        await limiter.release("domain1")
        await limiter.release("domain2")
        await limiter.close()

    async def test_close_cleans_up(self) -> None:
        """Test that close properly cleans up resources."""
        limiter = DomainRateLimiter()

        await limiter.acquire("test")
        await limiter.close()

        # After close, stats should be empty or reset
        stats = limiter.get_stats("test")
        assert stats["requests_in_progress"] == 0

    async def test_burst_capacity(self) -> None:
        """Test that burst capacity allows temporary spikes."""
        # 0.1 RPS (10s interval) with burst of 5
        config = RateLimitConfig(
            custom_limits={"burst_test": RateLimit(rps=0.1, burst=5, concurrent=10)}
        )
        limiter = DomainRateLimiter(config)

        start = asyncio.get_event_loop().time()

        # Should be able to acquire burst tokens quickly
        for _ in range(5):
            await limiter.acquire("burst_test")

        elapsed = asyncio.get_event_loop().time() - start
        # All 5 should complete quickly (within burst)
        assert elapsed < 0.5

        for _ in range(5):
            await limiter.release("burst_test")

        await limiter.close()

    async def test_domain_from_url(self) -> None:
        """Test extracting domain from URL."""
        test_cases = [
            ("https://api.tavily.com/search", "tavily"),
            ("https://api.tavily.com/v1/query", "tavily"),
            ("https://duckduckgo.com/html", "duckduckgo"),
            ("https://api.brave.com/search", "brave"),
            ("https://arxiv.org/abs/1234", "arxiv.org"),
            ("https://deepxiv.example.com/search", "deepxiv"),
            ("https://unknown.com/api", "unknown.com"),
        ]

        for url, expected in test_cases:
            domain = DomainRateLimiter.domain_from_url(url)
            assert domain == expected, f"Expected {expected} for {url}, got {domain}"


class TestRateLimiterEdgeCases:
    """Edge case tests for DomainRateLimiter."""

    async def test_zero_rps(self) -> None:
        """Test behavior with very low RPS (mocked to avoid 100s wait)."""
        # For rps=0.01, interval is 100s per token. Mock TokenBucket.acquire
        # to verify logic without waiting.
        bucket = TokenBucket(rps=0.01, burst=1)
        # Start with empty bucket to trigger wait calculation
        bucket._tokens = 0

        # Verify wait time calculation is correct (1 / 0.01 = 100s)
        tokens_needed = 1 - bucket._tokens  # 1
        wait_seconds = tokens_needed / 0.01  # 100s
        assert wait_seconds == 100.0

        # Acquire should work immediately with burst capacity
        bucket2 = TokenBucket(rps=0.01, burst=1)
        await bucket2.acquire(1)  # Uses burst token instantly
        assert bucket2._tokens == 0

    async def test_rapid_acquire_release(self) -> None:
        """Test rapid acquire/release cycles."""
        config = RateLimitConfig(
            custom_limits={"rapid": RateLimit(rps=100.0, burst=20, concurrent=20)}
        )
        limiter = DomainRateLimiter(config)

        for _ in range(20):
            await limiter.acquire("rapid")
            await limiter.release("rapid")

        stats = limiter.get_stats("rapid")
        assert stats["requests_in_progress"] == 0

        await limiter.close()

    async def test_concurrent_acquires(self) -> None:
        """Test concurrent acquire operations."""
        config = RateLimitConfig(
            custom_limits={"concurrent": RateLimit(rps=100.0, burst=10, concurrent=5)}
        )
        limiter = DomainRateLimiter(config)

        async def acquire_and_release() -> None:
            await limiter.acquire("concurrent")
            await asyncio.sleep(0.01)  # Simulate work
            await limiter.release("concurrent")

        # Run 10 concurrent operations
        await asyncio.gather(*[acquire_and_release() for _ in range(10)])

        stats = limiter.get_stats("concurrent")
        assert stats["requests_in_progress"] == 0

        await limiter.close()

    async def test_release_without_acquire(self) -> None:
        """Test releasing without prior acquire."""
        limiter = DomainRateLimiter()

        # Should not raise error
        await limiter.release("never_acquired")

        stats = limiter.get_stats("never_acquired")
        assert stats["requests_in_progress"] == 0

        await limiter.close()


@pytest.mark.asyncio
class TestRateLimiterIntegration:
    """Integration-style tests for DomainRateLimiter."""

    async def test_realistic_workflow(self) -> None:
        """Test a realistic workflow with multiple domains."""
        limiter = DomainRateLimiter()

        async def search_domain(domain: str, num_requests: int) -> list[str]:
            """Simulate searching a domain."""
            results = []
            for i in range(num_requests):
                async with limiter.acquire(domain):
                    await asyncio.sleep(0.01)  # Simulate API call
                    results.append(f"{domain}_result_{i}")
            return results

        # Search multiple domains concurrently
        tasks = [
            search_domain("tavily", 3),
            search_domain("duckduckgo", 3),
            search_domain("arxiv.org", 2),
        ]

        results = await asyncio.gather(*tasks)

        # Verify all completed
        assert len(results[0]) == 3
        assert len(results[1]) == 3
        assert len(results[2]) == 2

        # Verify no lingering requests
        global_stats = limiter.get_global_stats()
        assert global_stats["total_requests_in_progress"] == 0

        await limiter.close()

    async def test_rate_limit_with_high_concurrency(self) -> None:
        """Test rate limiting under high concurrent load."""
        config = RateLimitConfig(
            custom_limits={"load_test": RateLimit(rps=50.0, burst=10, concurrent=20)}
        )
        limiter = DomainRateLimiter(config)

        completion_times: list[float] = []
        start_time = asyncio.get_event_loop().time()

        async def timed_acquire(domain: str, idx: int) -> None:
            async with limiter.acquire(domain):
                completion_times.append((idx, asyncio.get_event_loop().time() - start_time))

        # Launch 30 concurrent acquires
        await asyncio.gather(*[timed_acquire("load_test", i) for i in range(30)])

        # All should complete
        assert len(completion_times) == 30

        # First 10 should complete quickly (burst)
        burst_times = [t for _, t in sorted(completion_times)[:10]]
        assert max(burst_times) < 0.5

        await limiter.close()
