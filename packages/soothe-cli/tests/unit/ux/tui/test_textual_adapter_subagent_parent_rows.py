"""Tests for subagent tool rows on parent Task cards (IG-300 elide parity)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.ux.task_namespace import scoped_subgraph_tool_key

from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _mount_subagent_inner_tool_row_if_resolved,
)
from soothe_cli.tui.widgets.messages import ToolCallMessage


@pytest.mark.asyncio
async def test_mount_subagent_inner_tool_row_resolves_parent_task_card() -> None:
    """Inner subgraph tools attach as rows when task scope binds to a mounted Task card."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    task_card = ToolCallMessage(
        "task",
        {"subagent_type": "explore", "description": "find files"},
        tool_call_id="tc-task",
    )
    adapter._tool_display_by_call_id["tc-task"] = task_card
    ns_key = ("delegated:subgraph-1",)
    router._namespace_bindings[ns_key] = ("tc-task", "explore", "")
    tracker = FileOpTracker(assistant_id="asst-1")

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="inner-grep-1",
        buffer_name="grep",
        parsed_args={"pattern": "TODO"},
        buffer_id="inner-grep-1",
        ns_key=ns_key,
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=tracker,
    )

    assert ok is True
    row_id = scoped_subgraph_tool_key(ns_key, "inner-grep-1")
    assert task_card.has_tool_call_row(row_id)
    assert adapter._tool_to_step[row_id] is task_card
    assert adapter._tool_display_by_call_id[row_id] is task_card
    adapter._set_spinner.assert_awaited_once_with("Tools")


@pytest.mark.asyncio
async def test_mount_subagent_inner_noop_for_main_namespace() -> None:
    """Main-agent tool stream must not use subgraph parent resolution."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router
    task_card = ToolCallMessage("task", {"subagent_type": "x"}, tool_call_id="tc-1")
    adapter._tool_display_by_call_id["tc-1"] = task_card
    ns_key = ("delegated",)
    router._namespace_bindings[ns_key] = ("tc-1", "x", "")

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="t1",
        buffer_name="grep",
        parsed_args={"pattern": "a"},
        buffer_id="t1",
        ns_key=ns_key,
        show_tool_ui=True,
        is_main_agent=True,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )

    assert ok is False
    assert not task_card.has_tool_call_row("t1")


@pytest.mark.asyncio
async def test_mount_subagent_inner_noop_when_task_scope_unbound() -> None:
    """Missing namespace binding leaves nothing to attach (standalone card suppressed)."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="t1",
        buffer_name="read_file",
        parsed_args={"path": "/x"},
        buffer_id="t1",
        ns_key=("unknown-namespace",),
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )

    assert ok is False


@pytest.mark.asyncio
async def test_mount_subagent_inner_unified_id_on_task_card_without_namespace() -> None:
    """Task-level unified ids mount on the Task card when namespace binding lags."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    task_card = ToolCallMessage(
        "task",
        {"subagent_type": "explore"},
        tool_call_id="FJS-02:s:task:0",
    )
    adapter._tool_display_by_call_id["FJS-02:s:task:0"] = task_card
    router._spawns_by_step_id["FJS-02"] = ("FJS-02:s:task:0", "explore", "FJS-02")
    unified = "FJS-02:t0:grep.0"

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id=unified,
        buffer_name="grep",
        parsed_args={"pattern": "TODO"},
        buffer_id=unified,
        ns_key=("tools:unbound",),
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )

    assert ok is True
    assert task_card.has_tool_call_row(unified)
    assert adapter._tool_to_step[unified] is task_card
