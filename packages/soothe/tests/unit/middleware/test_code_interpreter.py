"""Unit tests for CodeInterpreterMiddleware (langchain_quickjs bridge)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.config import SootheConfig
from soothe.middleware.code_interpreter import CodeInterpreterMiddleware

pytest.importorskip("langchain_quickjs")


def test_initialize_inner_succeeds_without_type_error() -> None:
    """Config fields must map to langchain_quickjs constructor kwargs (no TypeError)."""
    config = SootheConfig(
        agent={
            "code_interpreter": {
                "enabled": True,
                "ptc_allowlist": ["task"],
                "memory_limit_mb": 64,
                "timeout_seconds": 10,
                "max_ptc_calls": 25,
                "max_result_size": 8000,
                "console_capture": False,
                "snapshot_between_turns": True,
            }
        }
    )
    middleware = CodeInterpreterMiddleware(config=config)
    inner = middleware._initialize_inner()

    assert inner is not None
    assert middleware.tools
    assert middleware.tools[0].name == "eval"


@pytest.mark.asyncio
async def test_awrap_tool_call_passes_through_without_not_implemented() -> None:
    """Async agent runs must not delegate to QuickJS awrap_tool_call (not implemented)."""
    middleware = CodeInterpreterMiddleware(config=SootheConfig())
    middleware._initialize_inner()

    request = ToolCallRequest(
        tool_call={"name": "grep", "args": {"pattern": "deepxiv"}, "id": "tc-1"},
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    expected = ToolMessage(content="ok", tool_call_id="tc-1")
    handler = AsyncMock(return_value=expected)

    result = await middleware.awrap_tool_call(request, handler)

    assert result is expected
    handler.assert_awaited_once_with(request)
