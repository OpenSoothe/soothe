"""Parallel AgentLoop task delegations: per-step spawn keys and step-card rows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.ux.task_namespace import row_key_for_subgraph_tool

from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _mount_subagent_inner_tool_row_if_resolved,
)
from soothe_cli.tui.widgets.messages import ToolCallMessage


def test_step_scoped_namespace_bind_not_fifo_mismatch() -> None:
    """Deferred bind + register attaches explore namespace to the intended step."""
    router = StepTaskRouter()
    ns = ("tools:wrong-order",)
    router.on_subgraph_namespace(ns)
    router.register_task_spawn("YKF-02:s:task.0", "explore", step_id="YKF-02")
    assert router.resolve_task_scope(ns) == ("YKF-02:s:task.0", "explore", "YKF-02")


@pytest.mark.asyncio
async def test_task_card_gets_inner_tool_row_for_bound_step() -> None:
    """Inner explore tools attach to the Task delegation card, not the step card."""
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
        tool_call_id="functions.task:0",
    )
    adapter._tool_display_by_call_id["functions.task:0"] = task_card
    router._namespace_bindings[("tools:sub",)] = ("functions.task:0", "explore", "YKF-01")

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="functions.grep:2",
        buffer_name="grep",
        parsed_args={"pattern": "GoalEngine"},
        buffer_id="functions.grep:2",
        ns_key=("tools:sub",),
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )
    assert ok is True
    scope = ("functions.task:0", "explore", "YKF-01")
    row_id = row_key_for_subgraph_tool(("tools:sub",), "functions.grep:2", task_scope=scope)
    assert task_card.has_tool_call_row(row_id)
    assert adapter._tool_to_step[row_id] is task_card
