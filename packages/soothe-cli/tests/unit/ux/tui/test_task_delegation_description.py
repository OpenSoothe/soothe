"""Task delegation card description from stream overlay and step fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.textual_adapter._stream_formatting import (
    _ensure_task_delegation_card,
    enrich_task_delegation_args,
    refresh_task_cards_for_step,
    sync_task_delegation_cards_from_stream,
)
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.widgets.messages import CognitionStepMessage, ToolCallMessage


def test_enrich_task_delegation_args_uses_step_description_fallback() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    adapter._current_step_messages["JPV-01"] = CognitionStepMessage(
        "JPV-01",
        "Search for goal engine files",
    )
    out = enrich_task_delegation_args(adapter, "JPV-01:s:task:0", {})
    assert "goal engine" in str(out.get("description", ""))


def test_enrich_task_delegation_args_prefers_stream_overlay() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    adapter._current_step_messages["JPV-01"] = CognitionStepMessage(
        "JPV-01",
        "Step plan text",
    )
    overlay = {
        "JPV-01:s:task:0": {
            "description": "Detailed model task brief",
            "subagent_type": "explore",
        },
    }
    out = enrich_task_delegation_args(
        adapter,
        "JPV-01:s:task:0",
        {},
        streaming_overlay=overlay,
    )
    assert out["description"] == "Detailed model task brief"
    assert out["subagent_type"] == "explore"


@pytest.mark.asyncio
async def test_sync_task_cards_from_overlay_updates_header() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    adapter._current_step_messages["JPV-02"] = CognitionStepMessage(
        "JPV-02",
        "Find autopilot",
    )
    overlay = {
        "JPV-02:s:task:0": {
            "description": "Explore autopilot_cmd.py surface",
            "subagent_type": "explore",
        },
    }
    pending: dict = {}

    await sync_task_delegation_cards_from_stream(
        adapter,
        router,
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending,
        show_tool_ui=True,
    )

    card = adapter._current_tool_messages.get("JPV-02:s:task:0")
    assert isinstance(card, ToolCallMessage)
    assert card._args.get("subagent_type") == "explore"
    assert "autopilot_cmd" in str(card._args.get("description", ""))


@pytest.mark.asyncio
async def test_refresh_task_cards_for_step_after_early_empty_mount() -> None:
    """Task card created before step exists gets step description when step starts."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    tcid = "JPV-03:s:task:0"
    adapter._current_step_messages["JPV-03"] = CognitionStepMessage(
        "JPV-03",
        "Identify core architecture boundaries",
    )
    adapter._current_tool_messages[tcid] = ToolCallMessage(
        "task",
        {},
        tool_call_id=tcid,
    )
    adapter._tool_display_by_call_id[tcid] = adapter._current_tool_messages[tcid]
    router.register_task_spawn(tcid, "?", step_id="JPV-03")

    await refresh_task_cards_for_step(
        adapter,
        router,
        "JPV-03",
        streaming_overlay=None,
        pending_tool_calls_lc={},
        show_tool_ui=True,
    )

    card = adapter._current_tool_messages[tcid]
    assert "architecture" in str(card._args.get("description", ""))


@pytest.mark.asyncio
async def test_task_delegation_card_adds_step_activity_row() -> None:
    """Main-graph task shows on the step card and as a standalone task card."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    tcid = "WAA-01:s:task:0"
    step_w = CognitionStepMessage("WAA-01", "Search goal engine modules")
    adapter._current_step_messages["WAA-01"] = step_w
    args = {
        "subagent_type": "explore",
        "description": "Find GoalEngine entry points",
    }

    card = await _ensure_task_delegation_card(
        adapter,
        lookup_id=tcid,
        parsed_args=args,
        show_tool_ui=True,
    )

    assert isinstance(card, ToolCallMessage)
    assert adapter._tool_display_by_call_id[tcid] is card
    assert step_w.has_tool_call_row(tcid)
    assert adapter._tool_to_step[tcid] is step_w
    assert not card.has_tool_call_row(tcid)
