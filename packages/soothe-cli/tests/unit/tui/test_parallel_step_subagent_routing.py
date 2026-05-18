"""Parallel steps: subagent tools attach to the step encoded in unified tool_call_id."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _mount_subagent_inner_tool_row_if_resolved,
    _sync_task_delegation_step_row,
)
from soothe_cli.tui.widgets.messages import CognitionStepMessage


@pytest.mark.asyncio
async def test_second_step_explore_row_on_its_own_step_card() -> None:
    """Step B task delegation must not appear on step A's card when namespaces are queued."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    step_a = CognitionStepMessage("AAA-01", "Explore structure", id="st-a")
    step_b = CognitionStepMessage("BBB-02", "Identify entry points", id="st-b")
    adapter._current_step_messages["AAA-01"] = step_a
    adapter._current_step_messages["BBB-02"] = step_b

    router.on_subgraph_namespace(("tools:ns-a",))
    router.on_subgraph_namespace(("tools:ns-b",))
    router.register_task_spawn("functions.task:0", "explore", step_id="AAA-01")
    router.register_task_spawn("functions.task:0", "explore", step_id="BBB-02")

    assert _sync_task_delegation_step_row(
        adapter,
        lookup_id="AAA-01:s:task.0",
        display_args={"subagent_type": "explore", "description": "Explore structure"},
        bound_step_id="AAA-01",
    )
    assert _sync_task_delegation_step_row(
        adapter,
        lookup_id="BBB-02:s:task.0",
        display_args={"subagent_type": "explore", "description": "Identify entry points"},
        bound_step_id="BBB-02",
    )

    assert step_a.has_tool_call_row("AAA-01:s:task.0")
    assert not step_a.has_tool_call_row("BBB-02:s:task.0")
    assert step_b.has_tool_call_row("BBB-02:s:task.0")
    assert not step_b.has_tool_call_row("AAA-01:s:task.0")

    ok_b = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="BBB-02:t0:read_file.0",
        buffer_name="read_file",
        parsed_args={"file_path": "/pyproject.toml"},
        buffer_id="BBB-02:t0:read_file.0",
        ns_key=("tools:ns-b",),
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )
    assert ok_b is True
    assert step_b.has_tool_call_row("BBB-02:t0:read_file.0")
    assert not step_a.has_tool_call_row("BBB-02:t0:read_file.0")
    child = step_b._row_index["BBB-02:t0:read_file.0"]  # noqa: SLF001
    assert child.parent_tool_call_id == "BBB-02:s:task.0"
