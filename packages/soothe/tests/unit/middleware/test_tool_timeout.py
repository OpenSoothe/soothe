"""Tests for ToolTimeoutMiddleware (IG-512)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.middleware.tool_timeout import (
    DEFAULT_FILESYSTEM_TIMEOUT_SECONDS,
    DEFAULT_SUBAGENT_TIMEOUT_SECONDS,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    FILESYSTEM_TOOL_NAMES,
    SUBAGENT_TOOL_NAMES,
    ToolTimeoutMiddleware,
)


def _make_request(tool_name: str, tool_call_id: str = "test-id") -> MagicMock:
    """Create a mock ToolCallRequest."""
    request = MagicMock()
    request.tool_call = {
        "name": tool_name,
        "id": tool_call_id,
        "args": {},
    }
    return request


def _make_handler(result: str = "success") -> Callable[[Any], ToolMessage]:
    """Create a sync handler that returns a ToolMessage."""

    def handler(request: Any) -> ToolMessage:
        return ToolMessage(
            content=result,
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler


def _make_async_handler(result: str = "success") -> Callable[[Any], Awaitable[ToolMessage]]:
    """Create an async handler that returns a ToolMessage."""

    async def handler(request: Any) -> ToolMessage:
        await asyncio.sleep(0.01)  # Small delay to simulate work
        return ToolMessage(
            content=result,
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler


def _make_slow_async_handler(delay: float = 10.0) -> Callable[[Any], Awaitable[ToolMessage]]:
    """Create an async handler that delays beyond timeout."""

    async def handler(request: Any) -> ToolMessage:
        await asyncio.sleep(delay)
        return ToolMessage(
            content="slow result",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler


class TestToolTimeoutMiddleware:
    """Tests for ToolTimeoutMiddleware."""

    def test_default_timeout(self) -> None:
        """Default timeout should be 60s."""
        middleware = ToolTimeoutMiddleware()
        assert middleware._default_timeout == DEFAULT_TOOL_TIMEOUT_SECONDS

    def test_per_tool_timeout_override(self) -> None:
        """Per-tool timeout should override default."""
        middleware = ToolTimeoutMiddleware(
            per_tool_timeout={"grep": 15.0, "explore": 120.0},
        )
        assert middleware._get_timeout_for_tool("grep") == 15.0
        assert middleware._get_timeout_for_tool("explore") == 120.0

    def test_filesystem_category_timeout(self) -> None:
        """Filesystem tools should use filesystem category timeout."""
        middleware = ToolTimeoutMiddleware()
        for tool_name in FILESYSTEM_TOOL_NAMES:
            timeout = middleware._get_timeout_for_tool(tool_name)
            assert timeout == DEFAULT_FILESYSTEM_TIMEOUT_SECONDS

    def test_subagent_category_timeout(self) -> None:
        """Subagent tools should use subagent category timeout."""
        middleware = ToolTimeoutMiddleware()
        for tool_name in SUBAGENT_TOOL_NAMES:
            timeout = middleware._get_timeout_for_tool(tool_name)
            assert timeout == DEFAULT_SUBAGENT_TIMEOUT_SECONDS

        # Also test _subagent suffix pattern
        assert (
            middleware._get_timeout_for_tool("custom_subagent") == DEFAULT_SUBAGENT_TIMEOUT_SECONDS
        )

    def test_skip_tools_with_internal_timeout(self) -> None:
        """run_command should be skipped when skip_tools_with_internal_timeout=True."""
        middleware = ToolTimeoutMiddleware(skip_tools_with_internal_timeout=True)
        assert middleware._should_skip_timeout("run_command") is True
        assert middleware._should_skip_timeout("execute") is True
        assert middleware._should_skip_timeout("grep") is False

    def test_no_skip_when_disabled(self) -> None:
        """run_command should NOT be skipped when skip_tools_with_internal_timeout=False."""
        middleware = ToolTimeoutMiddleware(skip_tools_with_internal_timeout=False)
        assert middleware._should_skip_timeout("run_command") is False

    @pytest.mark.asyncio
    async def test_async_handler_completes_within_timeout(self) -> None:
        """Handler that completes within timeout should return result."""
        middleware = ToolTimeoutMiddleware(default_timeout_seconds=1.0)
        request = _make_request("test_tool")

        result = await middleware.awrap_tool_call(request, _make_async_handler("ok"))

        assert isinstance(result, ToolMessage)
        assert result.content == "ok"
        assert result.status != "error"

    @pytest.mark.asyncio
    async def test_async_handler_times_out(self) -> None:
        """Handler that exceeds timeout should return error ToolMessage."""
        middleware = ToolTimeoutMiddleware(default_timeout_seconds=0.1)  # 100ms timeout
        request = _make_request("slow_tool")

        result = await middleware.awrap_tool_call(request, _make_slow_async_handler(5.0))

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "timed out" in result.content.lower()
        assert middleware._timeout_count == 1

    @pytest.mark.asyncio
    async def test_skip_internal_timeout_tools(self) -> None:
        """run_command should bypass timeout wrapper and call handler directly."""
        middleware = ToolTimeoutMiddleware(
            default_timeout_seconds=0.1,
            skip_tools_with_internal_timeout=True,
        )
        request = _make_request("run_command")

        # Even with slow handler, should pass through without timeout
        result = await middleware.awrap_tool_call(request, _make_slow_async_handler(5.0))

        # Should NOT have timed out - handler was called directly
        # But since handler takes 5s > 0.1s timeout, if wrapper applied, it would fail
        # With skip=True, wrapper is NOT applied, so this test would take 5s
        # For test speed, we use a fast handler instead
        result = await middleware.awrap_tool_call(request, _make_async_handler("direct"))

        assert isinstance(result, ToolMessage)
        assert result.content == "direct"
        assert middleware._timeout_count == 0

    @pytest.mark.asyncio
    async def test_timeout_message_includes_tool_name(self) -> None:
        """Timeout error message should include tool name."""
        middleware = ToolTimeoutMiddleware(default_timeout_seconds=0.1)
        request = _make_request("my_slow_tool")

        result = await middleware.awrap_tool_call(request, _make_slow_async_handler(5.0))

        assert "my_slow_tool" in result.content
        assert "0.1s" in result.content

    @pytest.mark.asyncio
    async def test_multiple_timeouts_counted(self) -> None:
        """Timeout count should increment with each timeout."""
        middleware = ToolTimeoutMiddleware(default_timeout_seconds=0.1)
        request = _make_request("tool1")

        # First timeout
        await middleware.awrap_tool_call(request, _make_slow_async_handler(5.0))
        assert middleware._timeout_count == 1

        # Second timeout
        request2 = _make_request("tool2")
        await middleware.awrap_tool_call(request2, _make_slow_async_handler(5.0))
        assert middleware._timeout_count == 2

    def test_get_timeout_stats(self) -> None:
        """get_timeout_stats should return timeout count."""
        middleware = ToolTimeoutMiddleware()
        middleware._timeout_count = 5

        stats = middleware.get_timeout_stats()
        assert stats["timeout_count"] == 5

    @pytest.mark.asyncio
    async def test_per_tool_timeout_async(self) -> None:
        """Per-tool timeout should apply in async path."""
        middleware = ToolTimeoutMiddleware(
            default_timeout_seconds=10.0,
            per_tool_timeout={"fast_tool": 0.1},  # Short timeout for this tool
        )
        request = _make_request("fast_tool")

        result = await middleware.awrap_tool_call(request, _make_slow_async_handler(5.0))

        assert result.status == "error"
        assert "0.1s" in result.content


class TestTimeoutCategories:
    """Tests for timeout category classification."""

    def test_filesystem_tool_names(self) -> None:
        """Filesystem tool names should be categorized."""
        assert "read_file" in FILESYSTEM_TOOL_NAMES
        assert "grep" in FILESYSTEM_TOOL_NAMES
        assert "glob" in FILESYSTEM_TOOL_NAMES
        assert "write_file" in FILESYSTEM_TOOL_NAMES

    def test_subagent_tool_names(self) -> None:
        """Subagent tool names should be categorized."""
        assert "browser_use" in SUBAGENT_TOOL_NAMES
        assert "explore" in SUBAGENT_TOOL_NAMES
        assert "plan" in SUBAGENT_TOOL_NAMES
        assert "tacitus" in SUBAGENT_TOOL_NAMES
        assert "delegate" in SUBAGENT_TOOL_NAMES

    def test_unknown_tool_uses_default(self) -> None:
        """Unknown tools should use default timeout."""
        middleware = ToolTimeoutMiddleware(default_timeout_seconds=45.0)
        assert middleware._get_timeout_for_tool("unknown_tool") == 45.0
        assert middleware._get_timeout_for_tool("custom_agent") == 45.0
