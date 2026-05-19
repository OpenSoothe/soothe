"""Canonical subgraph tool ids and pending aliasing for task-card rows."""

from __future__ import annotations

import pytest

from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    alias_subgraph_pending_and_overlay,
    canonical_subgraph_tool_ids,
)


def test_canonical_subgraph_tool_ids_unifies_provider_id() -> None:
    ns = ("graphs", "sub-1")
    scope = ("task-tcid", "explore", "STEP-01")
    merge_id, row_key = canonical_subgraph_tool_ids(ns, "functions.grep:0", task_scope=scope)
    assert merge_id == "STEP-01:t0:grep.0"
    assert row_key == "STEP-01:t0:grep.0"


def test_alias_subgraph_pending_copies_overlay_to_unified_key() -> None:
    router = StepTaskRouter()
    ns = ("graphs", "sub-1")
    router._namespace_bindings[ns] = ("task-tcid", "explore", "STEP-01")
    pending = {
        "functions.read_file:0": {
            "name": "read_file",
            "args_str": '{"path":"/src/main.py"}',
            "is_complete_json": True,
            "emitted": False,
        },
    }
    overlay = {"functions.read_file:0": {"path": "/partial"}}
    alias_subgraph_pending_and_overlay(pending, overlay, router, ns)
    assert "STEP-01:t0:read_file.0" in pending
    assert pending["STEP-01:t0:read_file.0"]["name"] == "read_file"
    assert overlay["STEP-01:t0:read_file.0"]["path"] == "/partial"


def test_refresh_subgraph_tool_rows_from_overlay_updates_mounted_row() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from soothe_cli.tui.textual_adapter import TextualUIAdapter
    from soothe_cli.tui.textual_adapter._stream_formatting import (
        refresh_subgraph_tool_rows_from_overlay,
    )
    from soothe_cli.tui.widgets.messages import ToolCallMessage

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router
    ns = ("graphs", "sub-1")
    router._namespace_bindings[ns] = ("task-tcid", "explore", "STEP-01")
    task_card = ToolCallMessage("task", {}, tool_call_id="task-tcid")
    adapter._tool_display_by_call_id["task-tcid"] = task_card
    task_card.add_tool_call("STEP-01:t0:grep.0", "grep", {})
    overlay = {"STEP-01:t0:grep.0": {"pattern": "TODO"}}

    refresh_subgraph_tool_rows_from_overlay(
        adapter,
        router,
        ns_key=ns,
        streaming_overlay=overlay,
        pending_tool_calls_lc={},
    )

    assert task_card._row_index["STEP-01:t0:grep.0"].args.get("pattern") == "TODO"


def test_refresh_subgraph_parent_tool_row_updates_existing_row() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from soothe_cli.tui.textual_adapter import TextualUIAdapter
    from soothe_cli.tui.textual_adapter._stream_formatting import (
        refresh_subgraph_parent_tool_row,
    )
    from soothe_cli.tui.widgets.messages import ToolCallMessage

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router
    ns = ("graphs", "sub-1")
    router._namespace_bindings[ns] = ("task-tcid", "explore", "STEP-01")
    task_card = ToolCallMessage("task", {}, tool_call_id="task-tcid")
    adapter._tool_display_by_call_id["task-tcid"] = task_card
    task_card.add_tool_call("STEP-01:t0:grep.0", "grep", {})

    ok = refresh_subgraph_parent_tool_row(
        adapter,
        router,
        ns_key=ns,
        lookup_id="functions.grep:0",
        parsed_args={"pattern": "TODO"},
    )
    assert ok is True
    row = task_card._row_index["STEP-01:t0:grep.0"]
    assert row.args.get("pattern") == "TODO"


@pytest.mark.asyncio
async def test_wire_update_mounts_subgraph_row_with_args() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from soothe_cli.tui.file_ops import FileOpTracker
    from soothe_cli.tui.textual_adapter import TextualUIAdapter
    from soothe_cli.tui.textual_adapter._stream_tool_wire import apply_tool_call_wire_update
    from soothe_cli.tui.widgets.messages import CognitionStepMessage, ToolCallMessage

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router
    ns = ("graphs", "sub-1")
    router._namespace_bindings[ns] = ("task-tcid", "explore", "STEP-01")
    # IG-419: Inner subagent tools mount on step cards, not task cards
    step_card = CognitionStepMessage("STEP-01", "Explore workspace")
    adapter._current_step_messages["STEP-01"] = step_card
    task_card = ToolCallMessage(
        "task",
        {"subagent_type": "explore", "description": "scan"},
        tool_call_id="task-tcid",
    )
    adapter._tool_display_by_call_id["task-tcid"] = task_card
    pending: dict = {}
    overlay: dict = {}
    tracker = FileOpTracker(assistant_id="a")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": "soothe.stream.tool_call.update",
            "tool_call_id": "functions.grep:0",
            "name": "grep",
            "args": {"pattern": "TODO"},
        },
        ns_key=ns,
        show_tool_ui=True,
        pending_tool_calls_lc=pending,
        streaming_overlay=overlay,
        file_op_tracker=tracker,
    )

    assert handled is True
    # IG-419: Row now mounts on step card, not task card
    assert step_card.has_tool_call_row("STEP-01:t0:grep.0")
