"""Step-card tool stats: register unified main step tools before args arrive."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_cli.runtime.parse.tool_call_resolution import (
    is_execute_step_namespace,
    is_main_step_level_tool_call_id,
    is_step_card_tool_scope,
    is_task_level_subgraph_tool_call_id,
    should_ingest_tool_for_step_stats,
)
from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter, apply_tool_call_wire_update
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_is_main_step_level_tool_call_id() -> None:
    assert is_main_step_level_tool_call_id("BCO_01:s:read_file:0")
    assert not is_main_step_level_tool_call_id("BCO_01:s:task:0")
    assert not is_main_step_level_tool_call_id("BCO_01:t0:grep:1")
    assert not is_main_step_level_tool_call_id("grep:0")


def test_is_task_level_subgraph_tool_call_id() -> None:
    assert is_task_level_subgraph_tool_call_id("BCO_01:t0:grep:1")
    assert is_task_level_subgraph_tool_call_id("ZCH_01:t0:read_file:2")
    assert not is_task_level_subgraph_tool_call_id("BCO_01:s:read_file:0")
    assert not is_task_level_subgraph_tool_call_id("BCO_01:s:task:0")


def test_is_step_card_tool_scope() -> None:
    assert is_step_card_tool_scope(ns_key=())
    assert is_step_card_tool_scope(ns_key=("execute:abc",))
    assert not is_step_card_tool_scope(ns_key=("execute:abc", "tools:xyz"))
    assert is_execute_step_namespace(("execute:abc",))
    assert not is_execute_step_namespace(("execute:abc", "tools:xyz"))


def test_should_ingest_tool_for_step_stats_without_args() -> None:
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="read_file",
        tool_call_id="BCO_01:s:read_file:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="grep",
        tool_call_id="grep:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=False,
        tool_name="read_file",
        tool_call_id="BCO_01:t0:read_file:1",
        args_meaningful=False,
    )
    assert not should_ingest_tool_for_step_stats(
        is_step_card_scope=False,
        tool_name="read_file",
        tool_call_id="grep:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="grep",
        tool_call_id="BCO_01:s:grep:0",
        args_meaningful=True,
    )
    assert not should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="task",
        tool_call_id="BCO_01:s:task:0",
        args_meaningful=False,
    )


@pytest.mark.asyncio
async def test_wire_update_registers_main_step_tool_with_empty_args() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("BCO-01", "Read spec", id="stp-wire")
    adapter._current_step_messages["BCO-01"] = card
    router = StepTaskRouter()
    router.on_step_started("BCO-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:s:read_file:0",
            "name": "read_file",
            "args": {},
        },
        ns_key=(),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("BCO_01:s:read_file:0")
    assert card._stats_title_suffix() == " · 1 tool"


@pytest.mark.asyncio
async def test_wire_update_buffers_main_tool_before_step_card() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    router = StepTaskRouter()
    card = CognitionStepMessage("BCO-01", "Read spec", id="stp-wire-buffer")
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:s:read_file:0",
            "name": "read_file",
            "args": {},
        },
        ns_key=(),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert not card.has_tool_call_row("BCO_01:s:read_file:0")

    adapter._current_step_messages["BCO-01"] = card
    router.on_step_started("BCO-01")
    routed = router.route_pending_main_tools(
        adapter._current_step_messages,
        tool_to_step,
        display,
    )
    assert routed == 1
    assert card.has_tool_call_row("BCO_01:s:read_file:0")
    assert card._stats_title_suffix() == " · 1 tool"


@pytest.mark.asyncio
async def test_wire_update_fallback_ingests_subgraph_tool_without_task_binding() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("BCO-01", "List workspace", id="stp-wire-subgraph")
    adapter._current_step_messages["BCO-01"] = card
    router = StepTaskRouter()
    router.on_step_started("BCO-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:t0:ls:0",
            "name": "ls",
            "args": {"path": "."},
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("BCO_01:t0:ls:0")


@pytest.mark.asyncio
async def test_wire_update_registers_task_on_execute_namespace() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-task-exec")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:tool-abc123",
            "name": "task",
            "args": {
                "subagent_type": "explore",
                "description": "Survey RFCs 000-105",
            },
        },
        ns_key=("execute:c6612b5c",),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card._has_task_activity_body()
    assert card._iter_task_delegation_rows()
    assert router._spawns_by_task_id["ZCH_01:s:task:0"][1] == "explore"


@pytest.mark.asyncio
async def test_wire_update_registers_subgraph_tool_with_placeholder_args() -> None:
    """Subgraph placeholder args must still create a step-card row (tool name only)."""
    from soothe_cli.tui.tool_display import format_step_tool_activity_command

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-ph")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:read_file:2",
            "name": "read_file",
            "args": {"_subgraph_tool": True},
        },
        ns_key=("execute:abc", "tools:54045a8d"),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("ZCH_01:t0:read_file:2")
    assert format_step_tool_activity_command("read_file", {"_subgraph_tool": True}) == "ReadFile"


@pytest.mark.asyncio
async def test_subgraph_row_hydrates_args_from_late_raw_args_update() -> None:
    """IG-513: Subgraph tool args hydrate on SubAgent card (not step card)."""
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-late-args")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled_task = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "explore",
                "description": "Enumerate all files",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled_task is True

    handled_placeholder = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": {"_subgraph_tool": True},
        },
        ns_key=("execute:abc", "tools:late-args"),
        pending_tool_calls_lc={},
    )
    assert handled_placeholder is True

    # IG-513: Later stream update routes to SubAgent card
    handled_hydrate = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": '{"path":"/Users/xiamingchen/Workspace/mirasurf/soothe"}',
        },
        ns_key=("execute:abc", "tools:late-args"),
        pending_tool_calls_lc={},
    )
    assert handled_hydrate is True

    # IG-513: Check SubAgent card (not step card)
    subagent_key = "ZCH-01:t0"
    subagent_card = adapter._subagent_cards_by_key.get(subagent_key)
    assert subagent_card is not None, "SubAgent card should exist"
    text = str(subagent_card._step_task_activity_content())
    assert "ListFiles(" in text
    assert "mirasurf/soothe" in text


@pytest.mark.asyncio
async def test_subgraph_wire_string_args_render_for_list_files_and_glob() -> None:
    """Wire updates with string args must render previews for subagent tool rows."""
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-string-args")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled_task = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "explore",
                "description": "Enumerate all files in workspace",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled_task is True

    handled_list = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": '{"path":"/Users/xiamingchen/Workspace/mirasurf/soothe"}',
        },
        ns_key=("execute:abc", "tools:string-args"),
        pending_tool_calls_lc={},
    )
    assert handled_list is True

    handled_glob = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:glob:1",
            "name": "glob",
            "args": '{"glob_pattern":"**/*.py"}',
        },
        ns_key=("execute:abc", "tools:string-args"),
        pending_tool_calls_lc={},
    )
    assert handled_glob is True

    # IG-513: Subgraph tools now route to SubAgent cards, not step card
    subagent_key = "ZCH-01:t0"
    subagent_card = adapter._subagent_cards_by_key.get(subagent_key)
    assert subagent_card is not None, "SubAgent card should be created for task delegation"

    text = str(subagent_card._step_task_activity_content())
    assert "ListFiles(" in text
    assert "mirasurf/soothe" in text
    assert "Glob(" in text
    assert "**/*.py" in text


@pytest.mark.asyncio
async def test_subagent_wire_completed_finalizes_card_and_syncs_task_row() -> None:
    """Explore completed wire event must finalize SubAgent card (RFC-628, IG-513)."""
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_lifecycle_event

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    step = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-subagent-done")
    adapter._current_step_messages["ZCH-01"] = step
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "explore",
                "description": "Enumerate files",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:glob:0",
            "name": "glob",
            "args": {"glob_pattern": "**/*"},
        },
        ns_key=("execute:abc", "tools:done"),
        pending_tool_calls_lc={},
    )

    card = adapter._subagent_cards_by_key["ZCH-01:t0"]
    assert card._status == "running"

    scope: tuple[str, str, str] = ("ZCH-01:s:task:0", "explore", "ZCH-01")
    handled = _apply_subagent_wire_lifecycle_event(
        adapter,
        event_type="soothe.subagent.explore.completed",
        data={"duration_ms": 1200, "completion_status": "complete"},
        task_scope=scope,
    )
    assert handled is True
    assert card._status == "success"
    assert "ZCH-01:t0" not in adapter._subagent_cards_by_key
    task_rows = step._iter_task_delegation_rows()
    assert task_rows and task_rows[0].phase == "success"


def test_subagent_footer_ignores_server_step_tool_count() -> None:
    """SubAgent footer must use scope-local rows, not step-wide server totals."""
    from soothe_cli.tui.widgets.messages.cognition_subagent import create_subagent_card

    card = create_subagent_card(
        step_id="ZCH-01",
        description="Count files",
        subagent_type="explore",
        parent_step_id="ZCH-01",
        parent_task_key="ZCH-01:s:task:0",
        task_idx=0,
        id="subagent-test",
    )
    for i in range(7):
        card.add_tool_call(f"ZCH_01:t0:glob:{i}", "glob", {"glob_pattern": f"**/{i}"})
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()
    card.set_complete(True, 46426, 8, "Done")
    call_arg = card._status_widget.update.call_args[0][0]
    text = call_arg.plain if hasattr(call_arg, "plain") else str(call_arg)
    assert "7 tools" in text
    assert "8 tools" not in text
