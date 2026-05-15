"""Tests for parallel step tool_call_id → step_id binding on TextualUIAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_apply_tool_step_binding_migrates_row_between_step_cards() -> None:
    """Late binding moves a tool row from the namespace-fallback card to the bound step."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    wrong = CognitionStepMessage(step_id="s-wrong", description="Wrong step")
    right = CognitionStepMessage(step_id="s-right", description="Right step")
    adapter._current_step_messages["s-wrong"] = wrong
    adapter._current_step_messages["s-right"] = right
    tcid = "functions.grep:0"
    wrong.add_tool_call(tcid, "grep", {"pattern": "x"})
    adapter._tool_to_step[tcid] = wrong
    adapter._tool_display_by_call_id[tcid] = wrong

    adapter.apply_tool_step_binding(tcid, "s-right")

    assert not wrong.has_tool_call_row(tcid)
    assert right.has_tool_call_row(tcid)
    assert adapter._tool_to_step[tcid] is right
    assert adapter._tool_call_to_step_id[tcid] == "s-right"
    assert adapter._tool_display_by_call_id[tcid] is right
