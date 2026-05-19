"""Task delegation card description from stream overlay and step fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _ensure_task_delegation_card,
    enrich_task_delegation_args,
    refresh_task_cards_for_step,
    sync_task_delegation_cards_from_stream,
)
from soothe_cli.tui.widgets.messages import CognitionStepMessage


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


def test_enrich_task_delegation_args_parallel_steps_use_own_step_brief() -> None:
    """When a step starts, its task card must not show a sibling step's task description."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    adapter._current_step_messages["AAA-01"] = CognitionStepMessage(
        "AAA-01",
        "First step explores the repository",
    )
    adapter._current_step_messages["BBB-02"] = CognitionStepMessage(
        "BBB-02",
        "Second step maps architecture",
    )
    pending = {
        "AAA-01:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "First step explores the repository", "subagent_type": "explore"}'
            ),
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
        "BBB-02:s:task:0": {
            "name": "task",
            "args_str": "{}",
            "is_complete_json": False,
            "emitted": False,
            "is_main": True,
        },
    }
    out = enrich_task_delegation_args(
        adapter,
        "BBB-02:s:task:0",
        {},
        pending_tool_calls_lc=pending,
    )
    assert "Second step maps" in str(out.get("description", ""))
    assert "First step explores" not in str(out.get("description", ""))


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
    """IG-419: Task delegation syncs to step card row, not standalone card."""
    from soothe_sdk.ux.task_namespace import normalize_step_task_tool_call_id

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    step_card = CognitionStepMessage("JPV-02", "Find autopilot")
    adapter._current_step_messages["JPV-02"] = step_card
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

    # IG-419: No standalone card, row is on step card
    # Note: tool_call_id is normalized to use dots (JPV-02:s:task.0)
    normalized_tcid = normalize_step_task_tool_call_id("JPV-02", "JPV-02:s:task:0")
    assert adapter._current_tool_messages.get("JPV-02:s:task:0") is None
    assert step_card.has_tool_call_row(normalized_tcid)
    row = step_card._row_index.get(normalized_tcid)
    assert row is not None
    assert row.args.get("subagent_type") == "explore"
    assert "autopilot_cmd" in str(row.args.get("description", ""))


@pytest.mark.asyncio
async def test_refresh_task_cards_for_step_after_early_empty_mount() -> None:
    """IG-419: Task row on step card gets step description when refreshed."""
    from soothe_sdk.ux.task_namespace import normalize_step_task_tool_call_id

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    tcid = "JPV-03:s:task:0"
    # Note: normalized form uses dots
    normalized_tcid = normalize_step_task_tool_call_id("JPV-03", tcid)
    step_card = CognitionStepMessage(
        "JPV-03",
        "Identify core architecture boundaries",
    )
    adapter._current_step_messages["JPV-03"] = step_card
    # Add an empty task row that will be refreshed (use normalized id)
    step_card.add_tool_call(normalized_tcid, "explore", {})
    adapter._tool_display_by_call_id[normalized_tcid] = step_card
    router.register_task_spawn(tcid, "?", step_id="JPV-03")

    await refresh_task_cards_for_step(
        adapter,
        router,
        "JPV-03",
        streaming_overlay=None,
        pending_tool_calls_lc={},
        show_tool_ui=True,
    )

    # IG-419: Row is on step card, not standalone ToolCallMessage
    row = step_card._row_index.get(normalized_tcid)
    assert row is not None
    assert "architecture" in str(row.args.get("description", ""))


@pytest.mark.asyncio
async def test_task_delegation_card_adds_step_activity_row() -> None:
    """IG-419: Main-graph task shows on the step card row, no standalone card."""
    from soothe_sdk.ux.task_namespace import normalize_step_task_tool_call_id

    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    tcid = "WAA-01:s:task:0"
    # Note: normalized form uses dots
    normalized_tcid = normalize_step_task_tool_call_id("WAA-01", tcid)
    step_w = CognitionStepMessage("WAA-01", "Search goal engine modules")
    adapter._current_step_messages["WAA-01"] = step_w
    args = {
        "subagent_type": "explore",
        "description": "Find GoalEngine entry points",
    }

    # IG-419: Returns None, only syncs step row
    result = await _ensure_task_delegation_card(
        adapter,
        lookup_id=tcid,
        parsed_args=args,
        show_tool_ui=True,
    )

    assert result is None
    # IG-419: _tool_to_step maps normalized tcid to step widget
    assert adapter._tool_to_step[normalized_tcid] is step_w
    assert step_w.has_tool_call_row(normalized_tcid)
