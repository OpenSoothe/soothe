"""Tests for IG-295 LLM timeout retry with escalation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from soothe.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    LLMRateLimitMiddleware,
)


@pytest.fixture
def mock_request() -> ModelRequest:
    """Create mock model request."""
    return ModelRequest(
        model=MagicMock(),
        messages=[],
    )


@pytest.fixture
def mock_handler() -> AsyncMock:
    """Create mock handler that returns response."""
    return AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test response")]))


@pytest.fixture
def middleware_with_retry() -> LLMRateLimitMiddleware:
    """Create middleware with retry enabled."""
    return LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        call_timeout_adaptive=False,
        thread_local=True,
        retry_on_timeout=True,
        max_timeout_retries=2,
        timeout_retry_multiplier=2.0,
    )


@pytest.fixture
def middleware_no_retry() -> LLMRateLimitMiddleware:
    """Create middleware with retry disabled."""
    return LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        call_timeout_adaptive=False,
        thread_local=True,
        retry_on_timeout=False,
    )


def test_enhanced_timeout_error_creation() -> None:
    """Test EnhancedTimeoutError includes all metadata."""
    exc = EnhancedTimeoutError(
        timeout_seconds=480,
        retries=2,
        prompt_chars=96000,
        thread_id="thread-1",
    )

    assert exc.timeout_seconds == 480
    assert exc.retries == 2
    assert exc.prompt_chars == 96000
    assert exc.thread_id == "thread-1"

    # Message includes retry count and timeout
    msg = str(exc)
    assert "2 retries" in msg
    assert "480s" in msg
    assert "large prompt" in msg
    assert "96,000 chars" in msg


def test_enhanced_timeout_error_small_prompt() -> None:
    """Test EnhancedTimeoutError doesn't include large prompt tag for small prompts."""
    exc = EnhancedTimeoutError(
        timeout_seconds=120,
        retries=1,
        prompt_chars=30000,  # < 50000 threshold
        thread_id="thread-2",
    )

    msg = str(exc)
    assert "1 retries" in msg
    assert "120s" in msg
    assert "large prompt" not in msg


@pytest.mark.asyncio
async def test_retry_success_on_second_attempt(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
    mock_handler: AsyncMock,
) -> None:
    """Test retry succeeds on second attempt with escalated timeout."""
    call_count = 0

    async def timed_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("First attempt timeout")
        return ModelResponse(result=[AIMessage(content="success")])

    # Patch asyncio.wait_for to call handler directly (simulates timeout behavior)
    async def mock_wait_for(coro, timeout):
        # coro is the handler(request) call, we need to await it
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        response = await middleware_with_retry.awrap_model_call(mock_request, timed_handler)

        # Should succeed on second attempt
        assert response is not None
        assert call_count == 2  # First failed, second succeeded


@pytest.mark.asyncio
async def test_timeout_after_retries_exhausted(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test EnhancedTimeoutError raised after all retries exhausted."""
    call_count = 0

    async def always_timeout_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise TimeoutError(f"Attempt {call_count} timeout")

    # Mock wait_for to always timeout
    async def mock_wait_for(coro, timeout):
        # Await the handler which will raise TimeoutError
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(EnhancedTimeoutError) as exc_info:
            await middleware_with_retry.awrap_model_call(mock_request, always_timeout_handler)

        # Should have attempted 3 times (1 initial + 2 retries)
        assert call_count == 3

        # EnhancedTimeoutError should have metadata
        exc = exc_info.value
        assert exc.retries == 2
        assert exc.timeout_seconds >= 60  # Escalated timeout


@pytest.mark.asyncio
async def test_no_retry_when_disabled(
    middleware_no_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test no retry when retry_on_timeout=False."""
    call_count = 0

    async def timeout_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout")

    async def mock_wait_for(coro, timeout):
        return await coro

    # Should timeout immediately without retry
    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(TimeoutError):
            await middleware_no_retry.awrap_model_call(mock_request, timeout_handler)

        # Only one attempt
        assert call_count == 1


@pytest.mark.asyncio
async def test_timeout_escalation_on_retry(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test timeout escalates on each retry."""
    timeouts_used = []

    async def track_timeout_handler(req: ModelRequest) -> ModelResponse:
        raise TimeoutError("Always timeout")

    # Mock wait_for to track timeout values and raise TimeoutError
    async def mock_wait_for(coro, timeout):
        timeouts_used.append(timeout)
        # Await the coroutine which will raise TimeoutError
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(EnhancedTimeoutError):
            await middleware_with_retry.awrap_model_call(mock_request, track_timeout_handler)

        # Should have escalating timeouts: 60 -> 120 -> 240 (multiplier 2x)
        assert len(timeouts_used) == 3
        assert timeouts_used[0] == 60  # Base timeout
        assert timeouts_used[1] == 120  # 60 * 2 = 120
        assert timeouts_used[2] == 240  # 120 * 2 = 240


@pytest.mark.asyncio
async def test_thread_budget_cleanup_on_success(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
    mock_handler: AsyncMock,
) -> None:
    """Test successful request records in thread budget."""

    async def mock_wait_for(coro, timeout):
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        response = await middleware_with_retry.awrap_model_call(mock_request, mock_handler)

        # Should succeed and record request
        assert response is not None

        # Thread budget should exist
        budget = await middleware_with_retry._get_thread_budget("default")
        assert budget.request_times  # Request recorded


def test_calculate_retry_timeout_escalation(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test _calculate_retry_timeout escalates correctly."""
    # Attempt 0: base timeout
    timeout_0 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=0,
        request=mock_request,
    )
    assert timeout_0 == 60  # No escalation on initial attempt

    # Attempt 1: 2x escalation
    timeout_1 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=1,
        request=mock_request,
    )
    assert timeout_1 == 120  # 60 * 2 = 120

    # Attempt 2: 4x escalation
    timeout_2 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=2,
        request=mock_request,
    )
    assert timeout_2 == 240  # 60 * 4 = 240


def test_executor_error_classification_enhanced_timeout() -> None:
    """Test executor classifies EnhancedTimeoutError as execution (retryable)."""
    from soothe.core.agent import CoreAgent
    from soothe.core.agent_loop.engine.executor import Executor

    exc = EnhancedTimeoutError(
        timeout_seconds=480,
        retries=2,
        prompt_chars=96000,
        thread_id="test",
    )

    # Executor should classify as "execution" (not fatal)
    core_agent = MagicMock(spec=CoreAgent)
    executor = Executor(
        core_agent=core_agent,
        max_parallel_steps=16,
    )

    severity = executor._classify_error_severity(exc)
    assert severity == "execution"


def test_executor_error_extraction_enhanced_timeout() -> None:
    """Test executor extracts EnhancedTimeoutError metadata."""
    from soothe.core.agent import CoreAgent
    from soothe.core.agent_loop.engine.executor import Executor

    exc = EnhancedTimeoutError(
        timeout_seconds=480,
        retries=2,
        prompt_chars=96000,
        thread_id="test",
    )

    core_agent = MagicMock(spec=CoreAgent)
    executor = Executor(
        core_agent=core_agent,
        max_parallel_steps=16,
    )

    msg = executor._extract_error_message(exc, "fallback")
    assert "2 retries" in msg
    assert "480s timeout" in msg
    assert "large prompt" in msg
    assert "96,000 chars" in msg


def test_error_format_enhanced_timeout_large_prompt() -> None:
    """Test error format provides actionable suggestions for large prompt timeouts."""
    from soothe.utils.error_format import format_cli_error

    exc = EnhancedTimeoutError(
        timeout_seconds=480,
        retries=2,
        prompt_chars=96000,
        thread_id="test",
    )

    msg = format_cli_error(exc)
    assert "large prompt" in msg
    assert "simplifying" in msg or "splitting" in msg


def test_error_format_enhanced_timeout_general() -> None:
    """Test error format for general timeout after retries."""
    from soothe.utils.error_format import format_cli_error

    exc = EnhancedTimeoutError(
        timeout_seconds=120,
        retries=2,
        prompt_chars=30000,  # Not large
        thread_id="test",
    )

    msg = format_cli_error(exc)
    assert "retries" in msg
    assert "too complex" in msg or "Timeout" in msg


def test_error_format_generic_timeout() -> None:
    """Test error format for generic TimeoutError."""
    from soothe.utils.error_format import format_cli_error

    exc = TimeoutError("Operation timed out")

    msg = format_cli_error(exc)
    assert "retrying automatically" in msg or "timed out" in msg


@pytest.mark.asyncio
async def test_global_mode_retry(
    middleware_no_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test retry works in global (legacy) mode too."""
    # Create middleware with global mode + retry
    middleware_global = LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        call_timeout_adaptive=False,
        thread_local=False,  # Global mode
        retry_on_timeout=True,
        max_timeout_retries=2,
    )

    call_count = 0

    async def timeout_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise TimeoutError(f"Attempt {call_count}")

    async def mock_wait_for(coro, timeout):
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(EnhancedTimeoutError):
            await middleware_global.awrap_model_call(mock_request, timeout_handler)

        # Should retry in global mode too
        assert call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_backoff_between_retries(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test brief backoff sleep between retry attempts."""
    call_count = 0
    sleep_times = []

    async def timeout_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise TimeoutError(f"Attempt {call_count}")

    async def mock_wait_for(coro, timeout):
        return await coro

    # Mock sleep to track backoff
    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(EnhancedTimeoutError):
                await middleware_with_retry.awrap_model_call(mock_request, timeout_handler)

            # Should have sleep between retries (not after final)
            # Sleep times: 0.0 (attempt 1), 1.0 (attempt 2)
            assert len(sleep_times) == 2
            assert sleep_times[0] == 0.0  # First retry backoff (1.0 * 0)
            assert sleep_times[1] == 1.0  # Second retry backoff (1.0 * 1)
