"""Tests for PoliteHTTPClient and rate limiting components."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.subagents.tacitus.polite_http import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    DomainRateLimiter,
    PoliteClientContext,
    PoliteHTTPClient,
    RateLimit,
    RateLimitConfig,
    RetryableError,
    TokenBucket,
    get_global_polite_client,
    reset_global_client,
)


class TestRateLimit:
    """Tests for RateLimit dataclass."""

    def test_valid_rate_limit(self):
        limit = RateLimit(rps=2.0, burst=5, concurrent=10)
        assert limit.rps == 2.0
        assert limit.burst == 5
        assert limit.concurrent == 10

    def test_invalid_rps(self):
        with pytest.raises(ValueError, match="rps must be positive"):
            RateLimit(rps=0, burst=5, concurrent=10)
        with pytest.raises(ValueError, match="rps must be positive"):
            RateLimit(rps=-1, burst=5, concurrent=10)

    def test_invalid_burst(self):
        with pytest.raises(ValueError, match="burst must be at least 1"):
            RateLimit(rps=1.0, burst=0, concurrent=10)

    def test_invalid_concurrent(self):
        with pytest.raises(ValueError, match="concurrent must be at least 1"):
            RateLimit(rps=1.0, burst=5, concurrent=0)


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_get_default_limit(self):
        config = RateLimitConfig()
        limit = config.get_limit("unknown-domain")
        assert limit.rps == 0.5  # default
        assert limit.burst == 2
        assert limit.concurrent == 3

    def test_get_known_limit(self):
        config = RateLimitConfig()
        limit = config.get_limit("tavily")
        assert limit.rps == 1.0
        assert limit.burst == 3
        assert limit.concurrent == 5

    def test_multiplier(self):
        config = RateLimitConfig(multiplier=2.0)
        limit = config.get_limit("tavily")
        assert limit.rps == 2.0  # 1.0 * 2.0
        assert limit.burst == 6  # 3 * 2.0
        assert limit.concurrent == 10  # 5 * 2.0

    def test_custom_limit(self):
        config = RateLimitConfig(limits={"custom": RateLimit(rps=10.0, burst=20, concurrent=30)})
        limit = config.get_limit("custom")
        assert limit.rps == 10.0


class TestTokenBucket:
    """Tests for TokenBucket."""

    @pytest.mark.asyncio
    async def test_burst_allows_immediate_requests(self):
        bucket = TokenBucket(rps=1.0, burst=3)

        # First 3 requests should be immediate (burst)
        wait_times = []
        for _ in range(3):
            wait = await bucket.acquire()
            wait_times.append(wait)

        assert all(w == 0.0 for w in wait_times)

    @pytest.mark.asyncio
    async def test_rate_limiting_after_burst(self):
        bucket = TokenBucket(rps=10.0, burst=1)  # High RPS for faster test

        # First request
        wait1 = await bucket.acquire()
        assert wait1 == 0.0

        # Second request should wait
        start = time.monotonic()
        wait2 = await bucket.acquire()
        elapsed = time.monotonic() - start

        assert wait2 > 0
        # Token bucket calculates wait time, but actual sleep happens in caller
        # So elapsed should be very small (just the calculation time)
        assert elapsed < 0.01  # Should be nearly instant (no sleep in acquire)

    @pytest.mark.asyncio
    async def test_token_refill_over_time(self):
        bucket = TokenBucket(rps=10.0, burst=1)

        # Use the token
        await bucket.acquire()

        # Wait for refill
        await asyncio.sleep(0.15)

        # Should be immediate now
        wait = await bucket.acquire()
        assert wait == 0.0


class TestDomainRateLimiter:
    """Tests for DomainRateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        limiter = DomainRateLimiter()

        await limiter.acquire("test-domain")
        limiter.release("test-domain")

    @pytest.mark.asyncio
    async def test_concurrent_limit(self):
        config = RateLimitConfig(limits={"test": RateLimit(rps=100.0, burst=10, concurrent=2)})
        limiter = DomainRateLimiter(config)

        acquired = []

        async def try_acquire():
            try:
                await limiter.acquire("test")
                acquired.append(True)
                await asyncio.sleep(0.1)
                limiter.release("test")
            except Exception:
                pass

        # Try to acquire 5 times concurrently (limit is 2)
        tasks = [asyncio.create_task(try_acquire()) for _ in range(5)]
        await asyncio.sleep(0.05)

        # Should have acquired 2 (the concurrent limit)
        assert len(acquired) == 2

        # Wait for all to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_different_domains_independent(self):
        limiter = DomainRateLimiter()

        # Should be able to acquire from different domains independently
        await limiter.acquire("domain1")
        await limiter.acquire("domain2")

        limiter.release("domain1")
        limiter.release("domain2")

    @pytest.mark.asyncio
    async def test_release_on_exception(self):
        limiter = DomainRateLimiter()
        # Create semaphore with known initial value
        semaphore = asyncio.Semaphore(3)
        limiter._semaphores["test"] = semaphore

        # Mock bucket to raise exception
        limiter._buckets["test"] = MagicMock()
        limiter._buckets["test"].acquire = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            await limiter.acquire("test")

        # Semaphore should be released (back to original value)
        assert limiter._semaphores["test"]._value == 3


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60.0)
        mock_func = AsyncMock(return_value="success")

        result = await cb.call(mock_func, "arg")

        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failures == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60.0)
        mock_func = AsyncMock(side_effect=ValueError("error"))

        # 3 failures should open circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(mock_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.failures == 3

    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=60.0)
        mock_func = AsyncMock(side_effect=ValueError("error"))

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(mock_func)

        assert cb.state == CircuitBreakerState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(mock_func)

    @pytest.mark.asyncio
    async def test_half_open_then_close(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=0.1, half_open_max=2)
        mock_func = AsyncMock(return_value="success")

        # Open the circuit
        failing_func = AsyncMock(side_effect=ValueError("error"))
        with pytest.raises(ValueError):
            await cb.call(failing_func)

        # Wait for reset timeout
        await asyncio.sleep(0.15)

        # Should enter half-open and succeed
        result = await cb.call(mock_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # Second success should close circuit
        result = await cb.call(mock_func)
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=0.1)

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("error")))

        await asyncio.sleep(0.15)

        # Fail in half-open should reopen
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("error")))

        assert cb.state == CircuitBreakerState.OPEN


class TestPoliteHTTPClient:
    """Tests for PoliteHTTPClient."""

    @pytest.mark.asyncio
    async def test_successful_request(self):
        client = PoliteHTTPClient()
        mock_request = AsyncMock(return_value={"status": 200, "data": "ok"})

        result = await client.request("GET", "https://example.com/test", request_func=mock_request)

        assert result == {"status": 200, "data": "ok"}
        mock_request.assert_called_once_with("GET", "https://example.com/test")

    @pytest.mark.asyncio
    async def test_retry_on_retryable_error(self):
        client = PoliteHTTPClient(max_retries=2, base_delay=0.01)
        mock_request = AsyncMock(
            side_effect=[
                TimeoutError(),
                {"status": 200, "data": "ok"},
            ]
        )

        result = await client.request("GET", "https://example.com/test", request_func=mock_request)

        assert result == {"status": 200, "data": "ok"}
        assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_error(self):
        client = PoliteHTTPClient(max_retries=2)
        mock_request = AsyncMock(side_effect=ValueError("not retryable"))

        with pytest.raises(ValueError, match="not retryable"):
            await client.request("GET", "https://example.com/test", request_func=mock_request)

        assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_exhaust_retries(self):
        from soothe.subagents.tacitus.polite_http import (
            DomainRateLimiter,
            RateLimit,
            RateLimitConfig,
        )

        # Use a fast rate limiter to avoid 2s wait per retry
        fast_config = RateLimitConfig(
            limits={"example.com": RateLimit(rps=100.0, burst=10, concurrent=10)}
        )
        client = PoliteHTTPClient(
            rate_limiter=DomainRateLimiter(fast_config),
            max_retries=2,
            base_delay=0.01,
        )
        mock_request = AsyncMock(side_effect=TimeoutError("timeout"))

        with pytest.raises(asyncio.TimeoutError):
            await client.request("GET", "https://example.com/test", request_func=mock_request)

        assert mock_request.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_when_open(self):
        client = PoliteHTTPClient(enable_circuit_breaker=True, circuit_breaker_threshold=1)

        # Open the circuit
        with pytest.raises(ValueError):
            await client.request(
                "GET",
                "https://example.com/test",
                request_func=AsyncMock(side_effect=ValueError("error")),
            )

        # Next request should be blocked
        with pytest.raises(CircuitBreakerOpenError):
            await client.request(
                "GET",
                "https://example.com/test",
                request_func=AsyncMock(return_value="ok"),
            )

    @pytest.mark.asyncio
    async def test_domain_extraction(self):
        client = PoliteHTTPClient()

        assert client._extract_domain("https://api.example.com/path") == "api.example.com"
        assert client._extract_domain("http://example.com:8080/path") == "example.com"
        assert client._extract_domain("invalid-url") == "default"

    def test_is_retryable(self):
        client = PoliteHTTPClient()

        assert client._is_retryable(TimeoutError())
        assert client._is_retryable(ConnectionError())
        assert client._is_retryable(OSError())
        assert client._is_retryable(RetryableError("test"))

        # Non-retryable
        assert not client._is_retryable(ValueError())
        assert not client._is_retryable(TypeError())

    def test_calculate_delay(self):
        client = PoliteHTTPClient(base_delay=1.0, max_delay=10.0)

        # Exponential backoff: 1, 2, 4, 8...
        delay0 = client._calculate_delay(0)
        assert 0.9 <= delay0 <= 1.1  # Base delay with jitter

        delay1 = client._calculate_delay(1)
        assert 1.8 <= delay1 <= 2.2  # 2x base with jitter

        delay2 = client._calculate_delay(2)
        assert 3.6 <= delay2 <= 4.4  # 4x base with jitter

    @pytest.mark.asyncio
    async def test_get_post_convenience_methods(self):
        client = PoliteHTTPClient()
        mock_request = AsyncMock(return_value={"status": 200})

        with patch.object(client, "request", mock_request):
            await client.get("https://example.com")
            mock_request.assert_called_with("GET", "https://example.com")

            await client.post("https://example.com", data={"key": "value"})
            mock_request.assert_called_with("POST", "https://example.com", data={"key": "value"})


class TestPoliteClientContext:
    """Tests for PoliteClientContext."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        limiter = DomainRateLimiter()
        client = PoliteHTTPClient(rate_limiter=limiter)

        async with PoliteClientContext(client, "test-domain") as ctx:
            assert ctx._acquired
            # Semaphore should be acquired
            assert limiter._semaphores["test-domain"]._value == 2

        # Semaphore should be released
        assert limiter._semaphores["test-domain"]._value == 3

    @pytest.mark.asyncio
    async def test_release_on_exception(self):
        limiter = DomainRateLimiter()
        client = PoliteHTTPClient(rate_limiter=limiter)

        with pytest.raises(ValueError):
            async with PoliteClientContext(client, "test-domain"):
                raise ValueError("test error")

        # Semaphore should still be released
        assert limiter._semaphores["test-domain"]._value == 3


class TestGlobalClient:
    """Tests for global client functions."""

    def setup_method(self):
        reset_global_client()

    def teardown_method(self):
        reset_global_client()

    def test_get_global_client_creates_singleton(self):
        client1 = get_global_polite_client()
        client2 = get_global_polite_client()

        assert client1 is client2

    def test_get_global_client_with_params(self):
        client = get_global_polite_client(max_retries=5, base_delay=2.0)

        assert client.max_retries == 5
        assert client.base_delay == 2.0

    def test_reset_global_client(self):
        client1 = get_global_polite_client()
        reset_global_client()
        client2 = get_global_polite_client()

        assert client1 is not client2


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_full_request_flow(self):
        """Test a complete request with rate limiting and retry."""
        config = RateLimitConfig(
            limits={"example.com": RateLimit(rps=100.0, burst=10, concurrent=5)}
        )
        limiter = DomainRateLimiter(config)
        client = PoliteHTTPClient(
            rate_limiter=limiter,
            max_retries=1,
            base_delay=0.01,
            enable_circuit_breaker=True,
        )

        mock_request = AsyncMock(return_value={"status": 200, "data": "success"})

        result = await client.request(
            "GET",
            "https://example.com/api/data",
            request_func=mock_request,
        )

        assert result["status"] == 200
        assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_requests_respect_limits(self):
        """Test that concurrent requests respect rate limits."""
        config = RateLimitConfig(limits={"slow.com": RateLimit(rps=100.0, burst=5, concurrent=2)})
        limiter = DomainRateLimiter(config)
        client = PoliteHTTPClient(rate_limiter=limiter)

        results = []
        mock_request = AsyncMock(side_effect=lambda *args, **kwargs: {"id": len(results)})

        async def make_request():
            result = await client.request(
                "GET",
                "https://slow.com/api",
                request_func=mock_request,
            )
            results.append(result)

        # Launch 5 concurrent requests (limit is 2)
        tasks = [asyncio.create_task(make_request()) for _ in range(5)]
        await asyncio.gather(*tasks)

        assert len(results) == 5
        # Should have taken some time due to concurrency limit

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after failures."""
        client = PoliteHTTPClient(
            enable_circuit_breaker=True,
            circuit_breaker_threshold=2,
            circuit_breaker_reset_sec=0.1,
            circuit_breaker_half_open_max=1,  # Close after 1 success
            max_retries=0,
        )

        # Get the circuit breaker directly
        cb = client._get_circuit_breaker("example.com")

        # Manually open the circuit by simulating failures
        cb.failures = 2
        cb.state = CircuitBreakerState.OPEN
        cb.last_failure_time = time.monotonic()

        # Circuit should be open
        assert cb.is_open

        # Wait for reset timeout
        await asyncio.sleep(0.15)

        # Now the circuit breaker should allow a test request in half-open state
        # The request should succeed and close the circuit (with half_open_max=1)
        mock_success = AsyncMock(return_value="recovered")
        result = await client.request(
            "GET",
            "https://example.com",
            request_func=mock_success,
        )
        assert result == "recovered"
        assert cb.state == CircuitBreakerState.CLOSED  # Closed after 1 success
