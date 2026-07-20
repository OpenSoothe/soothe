"""Tests for circuit breaker implementation."""

import asyncio
import time

import pytest

from soothe_nano.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
)


class TestCircuitBreaker:
    """Test suite for CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open
        assert not breaker.is_half_open

    def test_record_failure_increments_counter(self):
        """Recording failures increments the failure count."""
        breaker = CircuitBreaker()
        breaker.record_failure()
        assert breaker._failure_count == 1

    def test_circuit_opens_at_threshold(self):
        """Circuit opens when failure threshold is reached."""
        breaker = CircuitBreaker(failure_threshold=3)

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.is_open

    def test_success_resets_failure_count_when_closed(self):
        """Success in CLOSED state resets failure count."""
        breaker = CircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._failure_count == 2

        breaker.record_success()
        assert breaker._failure_count == 0

    def test_reset_clears_state(self):
        """Reset returns circuit to initial CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open

        breaker.reset()
        assert breaker.is_closed
        assert breaker._failure_count == 0
        assert breaker._success_count == 0
        assert breaker._last_failure_time is None

    def test_sync_call_succeeds_when_closed(self):
        """Sync call succeeds when circuit is closed."""
        breaker = CircuitBreaker()

        def success_func():
            return "success"

        result = breaker.call(success_func)
        assert result == "success"

    def test_sync_call_raises_when_open(self):
        """Sync call raises CircuitBreakerOpenError when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()  # Open the circuit

        def any_func():
            return "should not reach"

        with pytest.raises(CircuitBreakerOpenError):
            breaker.call(any_func)

    def test_sync_call_records_failure_on_exception(self):
        """Sync call records failure when wrapped function raises."""
        breaker = CircuitBreaker(failure_threshold=5)

        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            breaker.call(failing_func)

        assert breaker._failure_count == 1

    def test_sync_call_records_success_on_completion(self):
        """Sync call records success when wrapped function completes."""
        breaker = CircuitBreaker()

        def success_func():
            return "success"

        breaker.call(success_func)
        assert breaker._failure_count == 0  # Reset by success

    def test_decorator_sync_function(self):
        """Decorator works with sync functions."""
        breaker = CircuitBreaker(failure_threshold=2)

        @breaker
        def my_function():
            return "decorated"

        result = my_function()
        assert result == "decorated"

    def test_get_stats_returns_current_state(self):
        """get_stats returns comprehensive circuit state."""
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=5,
            recovery_timeout=30.0,
            success_threshold=3,
        )
        breaker.record_failure()

        stats = breaker.get_stats()
        assert stats["name"] == "test-breaker"
        assert stats["state"] == "CLOSED"
        assert stats["failure_count"] == 1
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 30.0
        assert stats["success_threshold"] == 3


class TestCircuitBreakerAsync:
    """Async tests for CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_async_call_succeeds_when_closed(self):
        """Async call succeeds when circuit is closed."""
        breaker = CircuitBreaker()

        async def async_success():
            await asyncio.sleep(0.001)
            return "async success"

        result = await breaker.call_async(async_success)
        assert result == "async success"

    @pytest.mark.asyncio
    async def test_async_call_raises_when_open(self):
        """Async call raises CircuitBreakerOpenError when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()

        async def async_func():
            return "should not reach"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call_async(async_func)

    @pytest.mark.asyncio
    async def test_async_call_records_failure_on_exception(self):
        """Async call records failure when wrapped function raises."""
        breaker = CircuitBreaker(failure_threshold=5)

        async def async_failing():
            raise ValueError("async error")

        with pytest.raises(ValueError):
            await breaker.call_async(async_failing)

        assert breaker._failure_count == 1

    @pytest.mark.asyncio
    async def test_decorator_async_function(self):
        """Decorator works with async functions."""
        breaker = CircuitBreaker(failure_threshold=2)

        @breaker
        async def my_async_function():
            await asyncio.sleep(0.001)
            return "async decorated"

        result = await my_async_function()
        assert result == "async decorated"


class TestCircuitBreakerHalfOpen:
    """Tests for HALF_OPEN state transitions."""

    def test_half_open_after_timeout(self):
        """Circuit transitions to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        breaker.record_failure()
        assert breaker.is_open

        time.sleep(0.15)
        # Accessing is_half_open triggers state update
        assert breaker.is_half_open

    def test_open_on_failure_in_half_open(self):
        """Circuit returns to OPEN on failure in HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        breaker.record_failure()

        time.sleep(0.15)
        assert breaker.is_half_open

        breaker.record_failure()
        assert breaker.is_open

    def test_closed_after_success_threshold_in_half_open(self):
        """Circuit closes after success threshold in HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, success_threshold=2)
        breaker.record_failure()

        time.sleep(0.15)
        assert breaker.is_half_open

        breaker.record_success()
        assert breaker.is_half_open  # Need 2 successes

        breaker.record_success()
        assert breaker.is_closed


class TestCircuitBreakerConcurrency:
    """Tests for thread safety."""

    def test_concurrent_failure_recording(self):
        """Multiple threads can record failures safely."""
        breaker = CircuitBreaker(failure_threshold=100)

        import threading

        def record_failures():
            for _ in range(10):
                breaker.record_failure()

        threads = [threading.Thread(target=record_failures) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert breaker._failure_count == 50

    @pytest.mark.asyncio
    async def test_async_concurrent_calls(self):
        """Multiple async calls are handled safely."""
        breaker = CircuitBreaker(failure_threshold=100)

        async def async_task():
            await asyncio.sleep(0.001)
            return "done"

        tasks = [breaker.call_async(async_task) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(r == "done" for r in results)
