"""Parallel AgentLoop task delegations: per-step spawn keys and step-card rows."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _mount_subagent_inner_tool_row_if_resolved,
)
from soothe_cli.tui.widgets.messages import CognitionStepMessage
from soothe_sdk.ux.task_namespace import (
    maybe_bind_namespace,
    register_task_spawn_for_step,
    scoped_subgraph_tool_key,
)


def test_step_scoped_namespace_bind_not_fifo_mismatch() -> None:
    """Deferred bind + register attaches explore namespace to the intended step."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending: dict[str, list[tuple[str, ...]]] = {}
    ns = ("tools:wrong-order",)

    maybe_bind_namespace(
        bindings,
        queue,
        ns,
        active_step_id="YKF-02",
        spawns_by_step=spawns,
        pending_namespaces_by_step=pending,
    )
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        pending,
        ("functions.task:0", "explore", "YKF-02"),
    )
    assert bindings[ns][2] == "YKF-02"


@pytest.mark.asyncio
async def test_step_card_gets_inner_tool_row_for_bound_step() -> None:
    """Inner explore tools attach to the step card named in task scope."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    step = CognitionStepMessage(step_id="YKF-01", description="Explore goal engine")
    adapter._current_step_messages["YKF-01"] = step
    step.add_tool_call("functions.task:0", "task", {"subagent_type": "explore"})

    bindings = {("tools:sub",): ("functions.task:0", "explore", "YKF-01")}
    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        lookup_id="functions.grep:2",
        buffer_name="grep",
        parsed_args={"pattern": "GoalEngine"},
        buffer_id="functions.grep:2",
        ns_key=("tools:sub",),
        namespace_task_bindings=bindings,
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )
    assert ok is True
    row_id = scoped_subgraph_tool_key(("tools:sub",), "functions.grep:2")
    assert step.has_tool_call_row(row_id)
    assert adapter._tool_to_step[row_id] is step
