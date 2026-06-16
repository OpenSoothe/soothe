"""Step-card tool stats: register unified main step tools before args arrive."""

from __future__ import annotations

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
    assert "ReadFile(1)" in card._stats_title_suffix()


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
