"""Tests for tool-call kwargs registry captured at invocation time."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

# IG-519: Use ToolCallArgsMiddleware (semaphore removed from stack)
from soothe.middleware.tool_call_args_middleware import ToolCallArgsMiddleware
from soothe.middleware.tool_call_args_registry import (
    get_recorded_tool_call_args,
    init_tool_call_args_registry,
    record_tool_call_args_from_request,
)


def test_record_and_get_tool_call_args() -> None:
    init_tool_call_args_registry()
    request = ToolCallRequest(
        tool_call={
            "name": "read_file",
            "args": {"file_path": "/tmp/README.md"},
            "id": "functions.read_file:0",
        },
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    record_tool_call_args_from_request(request)
    assert get_recorded_tool_call_args("functions.read_file:0") == {
        "file_path": "/tmp/README.md",
    }


@pytest.mark.asyncio
async def test_awrap_tool_call_records_args_before_handler() -> None:
    init_tool_call_args_registry()
    middleware = ToolCallArgsMiddleware()
    request = ToolCallRequest(
        tool_call={
            "name": "edit_file",
            "args": {"file_path": "README.md", "old_string": "a", "new_string": "b"},
            "id": "functions.edit_file:3",
        },
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    handler = AsyncMock(
        return_value=ToolMessage(content="ok", tool_call_id="functions.edit_file:3")
    )

    await middleware.awrap_tool_call(request, handler)

    assert get_recorded_tool_call_args("functions.edit_file:3")["file_path"] == "README.md"
    handler.assert_awaited_once()
