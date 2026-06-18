"""Tests for IG-295 LLM timeout retry with escalation and IG-499 HTTP 429 retry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from soothe.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    LLMRateLimitMiddleware,
    _extract_retry_after_seconds,
    _is_api_rate_limit_error,
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
) -> None:
    """Test _calculate_retry_timeout escalates correctly."""
    # Attempt 0: base timeout
    timeout_0 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=0,
    )
    assert timeout_0 == 60  # No escalation on initial attempt

    # Attempt 1: 2x escalation
    timeout_1 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=1,
    )
    assert timeout_1 == 120  # 60 * 2 = 120

    # Attempt 2: 4x escalation
    timeout_2 = middleware_with_retry._calculate_retry_timeout(
        base_timeout=60,
        attempt=2,
    )
    assert timeout_2 == 240  # 60 * 4 = 240


def test_executor_error_classification_enhanced_timeout() -> None:
    """Test executor classifies EnhancedTimeoutError as execution (retryable)."""
    from soothe.foundation.core.agent import CoreAgent
    from soothe.foundation.loop.engine.executor import Executor

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
    from soothe.foundation.core.agent import CoreAgent
    from soothe.foundation.loop.engine.executor import Executor

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


def test_error_format_worker_subprocess_lost() -> None:
    """Pool worker exit should map to actionable daemon copy."""
    from soothe.utils.error_format import format_cli_error

    exc = RuntimeError(
        "Worker subprocess exited unexpectedly during query execution; "
        "check daemon logs for worker or model errors. (worker exit code: 0)"
    )
    msg = format_cli_error(exc)
    assert "Send your message again" in msg
    assert "Worker subprocess exited unexpectedly" not in msg


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
            # IG-499: backoff = 1.0 * timeout_attempts (after increment)
            # Sleep times: 1.0 (first retry), 2.0 (second retry)
            assert len(sleep_times) == 2
            assert sleep_times[0] == 1.0  # First retry backoff (1.0 * 1)
            assert sleep_times[1] == 2.0  # Second retry backoff (1.0 * 2)


def test_thread_id_from_request_uses_langgraph_configurable() -> None:
    """Parallel execute steps must not share the fallback 'default' LLM budget."""
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "loop-1__pCLJ-02"}}
    request = ModelRequest(model=MagicMock(), messages=[], runtime=runtime)

    assert LLMRateLimitMiddleware._thread_id_from_request(request) == "loop-1__pCLJ-02"


def test_thread_id_from_request_falls_back_to_default() -> None:
    request = ModelRequest(model=MagicMock(), messages=[])

    assert LLMRateLimitMiddleware._thread_id_from_request(request) == "default"


@pytest.mark.asyncio
async def test_parallel_steps_get_independent_llm_budgets(
    middleware_with_retry: LLMRateLimitMiddleware,
    mock_handler: AsyncMock,
) -> None:
    """Each LangGraph thread_id gets its own semaphore and RPM budget."""
    runtime_a = MagicMock()
    runtime_a.config = {"configurable": {"thread_id": "loop-1__pCLJ-01"}}
    runtime_b = MagicMock()
    runtime_b.config = {"configurable": {"thread_id": "loop-1__pCLJ-02"}}
    request_a = ModelRequest(model=MagicMock(), messages=[], runtime=runtime_a)
    request_b = ModelRequest(model=MagicMock(), messages=[], runtime=runtime_b)

    await middleware_with_retry.awrap_model_call(request_a, mock_handler)
    await middleware_with_retry.awrap_model_call(request_b, mock_handler)

    assert set(middleware_with_retry._thread_budgets) == {
        "loop-1__pCLJ-01",
        "loop-1__pCLJ-02",
    }


# ============================================================
# IG-499: HTTP 429 Rate Limit Retry Tests
# ============================================================


class MockRateLimitError(Exception):
    """Mock 429 rate limit error for testing."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message)
        # Simulate OpenAI RateLimitError structure
        self.response = MagicMock()
        self.response.status_code = 429
        self.response.headers = {}


class MockRateLimitErrorWithRetryAfterError(Exception):  # noqa: N818
    """Mock 429 error with retry-after header."""

    def __init__(self, retry_after: float = 5.0) -> None:
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
        self.response = MagicMock()
        self.response.status_code = 429
        self.response.headers = {"retry-after": str(retry_after)}


@pytest.fixture
def middleware_with_429_retry() -> LLMRateLimitMiddleware:
    """Create middleware with 429 retry enabled."""
    return LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_timeout=True,
        max_timeout_retries=2,
        timeout_retry_multiplier=2.0,
        # IG-499: 429 retry settings
        retry_on_rate_limit=True,
        max_rate_limit_retries=3,
        rate_limit_backoff_base=2.0,
        rate_limit_backoff_max=60.0,
        respect_retry_after_header=True,
    )


@pytest.fixture
def middleware_no_429_retry() -> LLMRateLimitMiddleware:
    """Create middleware with 429 retry disabled."""
    return LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_timeout=False,
        # IG-499: Disable 429 retry
        retry_on_rate_limit=False,
    )


def test_is_api_rate_limit_error_by_class_name() -> None:
    """Test detection by exception class name."""
    exc = MockRateLimitError()
    assert _is_api_rate_limit_error(exc) is True


def test_is_api_rate_limit_error_by_status_code() -> None:
    """Test detection by response.status_code attribute."""
    exc = Exception("Some error")
    exc.response = MagicMock()
    exc.response.status_code = 429
    assert _is_api_rate_limit_error(exc) is True


def test_is_api_rate_limit_error_by_keyword() -> None:
    """Test detection by keyword in error string."""
    exc1 = Exception("Error: 429 Too Many Requests")
    assert _is_api_rate_limit_error(exc1) is True

    exc2 = Exception("API rate limit exceeded")
    assert _is_api_rate_limit_error(exc2) is True

    exc3 = Exception("Request throttling detected")
    assert _is_api_rate_limit_error(exc3) is True


def test_is_api_rate_limit_error_non_rate_limit() -> None:
    """Test non-rate-limit errors are not detected."""
    exc = Exception("Some other error")
    exc.response = MagicMock()
    exc.response.status_code = 500
    assert _is_api_rate_limit_error(exc) is False


def test_extract_retry_after_seconds_present() -> None:
    """Test extracting retry-after header value."""
    exc = MockRateLimitErrorWithRetryAfterError(retry_after=10.0)
    result = _extract_retry_after_seconds(exc)
    assert result == 10.0


def test_extract_retry_after_seconds_missing() -> None:
    """Test returns None when retry-after header is missing."""
    exc = MockRateLimitError()
    result = _extract_retry_after_seconds(exc)
    assert result is None


def test_extract_retry_after_seconds_no_response() -> None:
    """Test returns None when exception has no response attribute."""
    exc = Exception("No response")
    result = _extract_retry_after_seconds(exc)
    assert result is None


@pytest.mark.asyncio
async def test_429_retry_success_on_second_attempt(
    middleware_with_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test 429 retry succeeds on second attempt."""
    call_count = 0

    async def rate_limit_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise MockRateLimitError()
        return ModelResponse(result=[AIMessage(content="success after retry")])

    async def mock_wait_for(coro, timeout):
        return await coro

    sleep_times = []

    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            response = await middleware_with_429_retry.awrap_model_call(
                mock_request, rate_limit_handler
            )

            # Should succeed on second attempt
            assert response is not None
            assert call_count == 2  # First failed, second succeeded
            # Should have one backoff sleep (between first and second attempt)
            assert len(sleep_times) == 1
            assert sleep_times[0] == 2.0  # backoff_base = 2.0


@pytest.mark.asyncio
async def test_429_retry_uses_retry_after_header(
    middleware_with_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test retry uses retry-after header when present."""
    call_count = 0

    async def rate_limit_with_retry_after(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise MockRateLimitErrorWithRetryAfterError(retry_after=5.0)
        return ModelResponse(result=[AIMessage(content="success")])

    async def mock_wait_for(coro, timeout):
        return await coro

    sleep_times = []

    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            response = await middleware_with_429_retry.awrap_model_call(
                mock_request, rate_limit_with_retry_after
            )

            assert response is not None
            # Should use retry-after value (5.0) instead of backoff_base (2.0)
            assert len(sleep_times) == 1
            assert sleep_times[0] == 5.0


@pytest.mark.asyncio
async def test_429_retry_exhausted(
    middleware_with_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test original 429 error raised after retries exhausted."""
    call_count = 0

    async def always_rate_limited(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise MockRateLimitError(f"Attempt {call_count}")

    async def mock_wait_for(coro, timeout):
        return await coro

    sleep_times = []

    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(MockRateLimitError):
                await middleware_with_429_retry.awrap_model_call(mock_request, always_rate_limited)

            # Should have attempted max_rate_limit_retries + 1 = 4 times
            assert call_count == 4
            # Should have 3 backoff sleeps (between 4 attempts)
            assert len(sleep_times) == 3
            # Exponential backoff: 2.0, 4.0, 8.0
            assert sleep_times[0] == 2.0  # 2.0 * 2^0
            assert sleep_times[1] == 4.0  # 2.0 * 2^1
            assert sleep_times[2] == 8.0  # 2.0 * 2^2


@pytest.mark.asyncio
async def test_429_no_retry_when_disabled(
    middleware_no_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test no retry when retry_on_rate_limit=False."""
    call_count = 0

    async def rate_limit_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise MockRateLimitError()

    async def mock_wait_for(coro, timeout):
        return await coro

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(MockRateLimitError):
            await middleware_no_429_retry.awrap_model_call(mock_request, rate_limit_handler)

        # Only one attempt, no retry
        assert call_count == 1


@pytest.mark.asyncio
async def test_429_backoff_capped_at_max(
    middleware_with_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test backoff is capped at rate_limit_backoff_max."""
    # Create middleware with low backoff_max to trigger cap
    middleware = LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_rate_limit=True,
        max_rate_limit_retries=5,
        rate_limit_backoff_base=10.0,
        rate_limit_backoff_max=30.0,  # Cap at 30s
        respect_retry_after_header=False,  # Force exponential backoff
    )

    call_count = 0

    async def always_rate_limited(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        raise MockRateLimitError()

    async def mock_wait_for(coro, timeout):
        return await coro

    sleep_times = []

    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(MockRateLimitError):
                await middleware.awrap_model_call(mock_request, always_rate_limited)

            # Check backoffs are capped at 30.0
            # Expected: 10.0, 20.0, 30.0 (capped), 30.0 (capped), 30.0 (capped)
            for sleep_time in sleep_times[2:]:  # After first 2
                assert sleep_time <= 30.0


@pytest.mark.asyncio
async def test_429_and_timeout_retry_separate_counters(
    middleware_with_429_retry: LLMRateLimitMiddleware,
    mock_request: ModelRequest,
) -> None:
    """Test 429 and timeout retries use separate counters."""
    call_count = 0

    async def mixed_error_handler(req: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Timeout on first call")
        if call_count == 2:
            raise MockRateLimitError("429 on second call")
        return ModelResponse(result=[AIMessage(content="success")])

    async def mock_wait_for(coro, timeout):
        return await coro

    sleep_times = []

    async def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            response = await middleware_with_429_retry.awrap_model_call(
                mock_request, mixed_error_handler
            )

            # Should succeed on third attempt (timeout retry + 429 retry)
            assert response is not None
            assert call_count == 3
            # Two sleeps: one for timeout backoff, one for 429 backoff
            assert len(sleep_times) == 2


def test_calculate_rate_limit_backoff_exponential() -> None:
    """Test exponential backoff calculation."""
    middleware = LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_rate_limit=True,
        max_rate_limit_retries=3,
        rate_limit_backoff_base=2.0,
        rate_limit_backoff_max=60.0,
        respect_retry_after_header=True,
    )

    # Attempt 0: 2.0 * 2^0 = 2.0
    backoff_0 = middleware._calculate_rate_limit_backoff(attempt=0, exc=None)
    assert backoff_0 == 2.0

    # Attempt 1: 2.0 * 2^1 = 4.0
    backoff_1 = middleware._calculate_rate_limit_backoff(attempt=1, exc=None)
    assert backoff_1 == 4.0

    # Attempt 2: 2.0 * 2^2 = 8.0
    backoff_2 = middleware._calculate_rate_limit_backoff(attempt=2, exc=None)
    assert backoff_2 == 8.0


def test_calculate_rate_limit_backoff_respects_retry_after() -> None:
    """Test retry-after header overrides exponential backoff."""
    middleware = LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_rate_limit=True,
        max_rate_limit_retries=3,
        rate_limit_backoff_base=2.0,
        rate_limit_backoff_max=60.0,
        respect_retry_after_header=True,
    )
    exc = MockRateLimitErrorWithRetryAfterError(retry_after=15.0)

    # Should use retry-after value instead of exponential
    backoff = middleware._calculate_rate_limit_backoff(attempt=0, exc=exc)
    assert backoff == 15.0


def test_calculate_rate_limit_backoff_retry_after_capped() -> None:
    """Test retry-after value is capped at backoff_max."""
    middleware = LLMRateLimitMiddleware(
        requests_per_minute=120,
        max_concurrent_requests_per_thread=10,
        call_timeout_seconds=60,
        call_timeout_max_seconds=240,
        thread_local=True,
        retry_on_rate_limit=True,
        max_rate_limit_retries=3,
        rate_limit_backoff_base=2.0,
        rate_limit_backoff_max=60.0,
        respect_retry_after_header=True,
    )
    # retry_after > backoff_max (60.0)
    exc = MockRateLimitErrorWithRetryAfterError(retry_after=120.0)

    backoff = middleware._calculate_rate_limit_backoff(attempt=0, exc=exc)
    assert backoff == 60.0  # Capped at backoff_max
