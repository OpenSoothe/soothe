"""Host Executor error classification vs rate-limit detection.

Moved from soothe-nano (IG-641): these tests exercise StrangeLoop Executor
and execute_steps helpers, which must not live in nano.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_nano.utils.llm.invoke_policy import EnhancedTimeoutError

from soothe.coreagent import SootheNanoAgent as CoreAgent
from soothe.sloop.engine.executor import Executor
from soothe.sloop.stages.execute.execute import _is_rate_limit_error


def test_executor_error_classification_enhanced_timeout() -> None:
    """Test executor classifies EnhancedTimeoutError as execution (retryable)."""
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

    severity = executor._classify_error_severity(exc)
    assert severity == "execution"


def test_executor_error_extraction_enhanced_timeout() -> None:
    """Test executor extracts EnhancedTimeoutError metadata."""
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


def test_executor_timeout_not_misclassified_as_rate_limit() -> None:
    """TimeoutError with 'llm_rate_limit middleware' text must NOT be rate-limit.

    The TimeoutError message from graph_interrupt.py includes a suggestion to enable
    llm_rate_limit middleware. This 'rate_limit' substring must not trigger
    rate limit detection.
    """
    exc = TimeoutError(
        "LLM stream chunk timeout after 120s - no response received. "
        "Check LLM API connectivity or enable llm_rate_limit middleware for configurable timeouts."
    )

    core_agent = MagicMock(spec=CoreAgent)
    executor = Executor(
        core_agent=core_agent,
        max_parallel_steps=16,
    )

    msg = executor._extract_error_message(exc, "fallback")
    assert msg == "Request timed out", f"Expected 'Request timed out' but got '{msg}'"

    assert _is_rate_limit_error(msg) is False, (
        "Timeout should not be classified as rate limit error"
    )
