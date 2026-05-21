"""Step-card tool stats: register unified main step tools before args arrive."""

from __future__ import annotations

import pytest
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_cli.runtime.parse.tool_call_resolution import (
    is_main_step_level_tool_call_id,
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


def test_should_ingest_tool_for_step_stats_without_args() -> None:
    assert should_ingest_tool_for_step_stats(
        is_main_agent=True,
        tool_name="read_file",
        tool_call_id="BCO_01:s:read_file:0",
        args_meaningful=False,
    )
    assert not should_ingest_tool_for_step_stats(
        is_main_agent=False,
        tool_name="read_file",
        tool_call_id="BCO_01:t0:read_file:1",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_main_agent=True,
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
