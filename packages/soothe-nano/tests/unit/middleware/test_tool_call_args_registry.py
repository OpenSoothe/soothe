"""Tests for tool-call kwargs registry captured at invocation time."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

# IG-519: Use ToolCallArgsMiddleware (semaphore removed from stack)
from soothe_nano.middleware.tool_call_args_middleware import ToolCallArgsMiddleware
from soothe_nano.middleware.tool_call_args_registry import (
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


def test_main_middleware_stack_mounts_tool_call_args_recording() -> None:
    """The main CoreAgent stack must record tool-call args for TUI display.

    Regression guard (IG-519): removing ToolConcurrencyMiddleware from
    ``build_soothe_middleware_stack`` silently dropped the only caller of
    ``record_tool_call_args_from_request`` on the main path, so the executor's
    stream code (``ingest_invocation_registry``) found an empty registry and the
    TUI stopped showing tool-call args on step and non-explore subagent
    activities. The args-recording middleware must stay in the main stack.
    """
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    stack = build_soothe_middleware_stack(SootheConfig(), policy=None)
    assert any(type(m).__name__ == "ToolCallArgsMiddleware" for m in stack)


def test_tool_call_args_middleware_wraps_edit_coalescing() -> None:
    """ToolCallArgs must be outer so coalesced edit_file calls still record kwargs."""
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    names = [type(m).__name__ for m in build_soothe_middleware_stack(SootheConfig(), policy=None)]
    args_idx = names.index("ToolCallArgsMiddleware")
    coalesce_idx = names.index("EditCoalescingMiddleware")
    assert args_idx < coalesce_idx


@pytest.mark.asyncio
async def test_outer_tool_call_args_records_before_coalescing_intercepts_edit_file() -> None:
    """Regression: edit_file cards need args even when coalescing never calls the tool handler."""
    from soothe_nano.middleware.edit_coalescing import (
        EditCoalescingConfig,
        EditCoalescingMiddleware,
    )

    init_tool_call_args_registry()
    coalescing = EditCoalescingMiddleware(
        config=EditCoalescingConfig(detection_window_ms=60_000),
    )
    args_middleware = ToolCallArgsMiddleware()
    request = ToolCallRequest(
        tool_call={
            "name": "edit_file",
            "args": {
                "file_path": "/tmp/example.py",
                "old_string": "foo",
                "new_string": "bar",
            },
            "id": "functions.edit_file:9",
        },
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    inner_handler = AsyncMock(
        return_value=ToolMessage(content="should not run", tool_call_id="functions.edit_file:9")
    )

    async def coalescing_handler(req: ToolCallRequest) -> ToolMessage:
        return await coalescing.awrap_tool_call(req, inner_handler)

    # Do not await coalescing's future; intercept queues the edit and waits on the window.
    record_task = asyncio.create_task(args_middleware.awrap_tool_call(request, coalescing_handler))
    await asyncio.sleep(0)
    record_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await record_task

    recorded = get_recorded_tool_call_args("functions.edit_file:9")
    assert recorded.get("file_path") == "/tmp/example.py"
    assert recorded.get("old_string") == "foo"
    assert recorded.get("new_string") == "bar"
    inner_handler.assert_not_awaited()
