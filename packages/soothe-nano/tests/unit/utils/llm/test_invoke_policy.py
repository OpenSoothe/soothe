"""Tests for planner/direct LLM invoke policy (timeout + retry)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from soothe_deepagents.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    LLMRateLimitRegistry,
)

from soothe_nano.config.models import LLMRateLimitConfig
from soothe_nano.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe_nano.utils.llm.structured import StructuredOutputError


@pytest.fixture(autouse=True)
def _reset_llm_rate_limit_registry() -> None:
    LLMRateLimitRegistry.reset_for_tests()


class MockRateLimitError(Exception):
    """Mock provider 429 for invoke policy tests."""

    def __init__(self, message: str = "Error code: 429 - throttling") -> None:
        super().__init__(message)
        self.response = type("Resp", (), {"status_code": 429, "headers": {}})()


def test_llm_rate_limit_config_from_defaults() -> None:
    assert llm_rate_limit_config_from(None).retry_on_rate_limit is True


@pytest.mark.asyncio
async def test_invoke_policy_returns_on_success() -> None:
    factory = AsyncMock(return_value="ok")
    config = LLMRateLimitConfig(call_timeout_seconds=30, retry_on_timeout=False)

    result = await await_with_llm_call_policy(factory, config=config, thread_id="t1")

    assert result == "ok"
    factory.assert_awaited_once()


@pytest.mark.asyncio
async def test_invoke_policy_retries_timeout_then_succeeds() -> None:
    calls = 0

    async def slow_then_ok() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError
        return "done"

    config = LLMRateLimitConfig(retry_on_timeout=True, max_timeout_retries=1)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await await_with_llm_call_policy(slow_then_ok, config=config)

    assert result == "done"
    assert calls == 2


@pytest.mark.asyncio
async def test_invoke_policy_raises_enhanced_timeout_when_exhausted() -> None:
    async def always_slow() -> str:
        raise TimeoutError

    config = LLMRateLimitConfig(retry_on_timeout=True, max_timeout_retries=0)

    with pytest.raises(EnhancedTimeoutError):
        await await_with_llm_call_policy(always_slow, config=config)


@pytest.mark.asyncio
async def test_invoke_policy_retries_429_then_succeeds() -> None:
    calls = 0

    async def rate_limited_then_ok() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MockRateLimitError()
        return "done"

    config = LLMRateLimitConfig(
        retry_on_rate_limit=True,
        max_rate_limit_retries=2,
        rate_limit_backoff_base=1.0,
        respect_retry_after_header=False,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await await_with_llm_call_policy(rate_limited_then_ok, config=config)

    assert result == "done"
    assert calls == 2


@pytest.mark.asyncio
async def test_invoke_policy_429_retry_uses_shorter_timeout() -> None:
    """After 429, retries should use rate_limit_retry_timeout_seconds not call_timeout."""
    calls = 0
    captured_timeouts: list[int | float] = []
    real_wait_for = asyncio.wait_for

    async def rate_limited_then_ok() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MockRateLimitError()
        return "done"

    async def tracking_wait_for(awaitable: Any, *, timeout: int | float) -> Any:
        captured_timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    config = LLMRateLimitConfig(
        call_timeout_seconds=600,
        rate_limit_retry_timeout_seconds=45,
        retry_on_rate_limit=True,
        max_rate_limit_retries=2,
        rate_limit_backoff_base=1.0,
        respect_retry_after_header=False,
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch(
            "soothe_deepagents.middleware.llm_rate_limit.asyncio.wait_for",
            side_effect=tracking_wait_for,
        ),
    ):
        result = await await_with_llm_call_policy(
            rate_limited_then_ok,
            config=config,
            thread_id="loop-1",
        )

    assert result == "done"
    assert calls == 2
    assert captured_timeouts == [600, 45]


@pytest.mark.asyncio
async def test_invoke_policy_retries_wrapped_structured_output_429() -> None:
    """StructuredOutputError wrapping RateLimitError should still retry."""
    calls = 0
    root = MockRateLimitError()

    async def wrapped_429_then_ok() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StructuredOutputError(f"structured model invoke failed: {root}") from root
        return "done"

    config = LLMRateLimitConfig(
        retry_on_rate_limit=True,
        max_rate_limit_retries=1,
        rate_limit_backoff_base=1.0,
        respect_retry_after_header=False,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await await_with_llm_call_policy(wrapped_429_then_ok, config=config)

    assert result == "done"
    assert calls == 2
