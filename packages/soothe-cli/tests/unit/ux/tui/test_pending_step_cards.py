"""Step cards mount on run start; pending steps live in the plan quick view only."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _pop_step_card_from_adapter,
    cleanup_stale_plan_step_cards,
)
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage


@pytest.mark.asyncio
async def test_plan_decision_does_not_mount_pending_step_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    steps = [
        {"id": "WAA-01", "description": "Ready step"},
        {"id": "WAA-02", "description": "Blocked on WAA-01"},
    ]
    await cleanup_stale_plan_step_cards(adapter, steps=steps)

    adapter._mount_message.assert_not_called()
    assert adapter._current_step_messages == {}


@pytest.mark.asyncio
async def test_plan_decision_replan_removes_stale_pending_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    stale = CognitionStepMessage("OLD-01", "Dropped", id="step-old")
    adapter._current_step_messages["OLD-01"] = stale
    stale._status = "pending"

    await cleanup_stale_plan_step_cards(
        adapter,
        steps=[{"id": "NEW-01", "description": "Kept"}],
    )
    assert "OLD-01" not in adapter._current_step_messages
    adapter._mount_message.assert_not_called()


@pytest.mark.asyncio
async def test_step_started_mounts_running_card() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    card = CognitionStepMessage("WAA-01", "Step one", id="step-one")
    await adapter._mount_message(card)
    adapter._current_step_messages["WAA-01"] = card
    card.set_running()
    assert card._status == "running"
    adapter._mount_message.assert_awaited_once()


def test_future_step_without_card_stays_off_message_list() -> None:
    """Tools for a not-yet-started step must not create a pending card."""
    router = StepTaskRouter()
    active = CognitionStepMessage("WAA-01", "Step one", id="step-one")
    active.set_running()
    step_cards = {"WAA-01": active}

    router.maybe_promote_step_to_running(
        active,
        "WAA_01:s:grep:0",
        step_cards=step_cards,
    )

    assert active._status == "running"
    assert "WAA-02" not in step_cards


def test_active_step_promotes_before_step_started_event() -> None:
    """Tools may arrive before step.started; the active step may show running early."""
    router = StepTaskRouter()
    card = CognitionStepMessage("WAA-01", "Step one", id="step-one")
    step_cards = {"WAA-01": card}

    card.add_tool_call("WAA_01:s:grep:0", "grep", {"pattern": "x"})
    router.maybe_promote_step_to_running(
        card,
        "WAA_01:s:grep:0",
        step_cards=step_cards,
    )

    assert card._status == "running"


@pytest.mark.asyncio
async def test_completed_step_card_stays_mounted_after_pop() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    card = CognitionStepMessage("LQF-02", "Analyze failures", id="step-two")
    await adapter._mount_message(card)
    adapter._current_step_messages["LQF-02"] = card
    card.set_running()
    popped = _pop_step_card_from_adapter(adapter, "LQF-02")
    assert popped is card
    popped.set_complete(False, 2000, 5, "Failed")
    assert popped._status == "error"
    assert "LQF-02" not in adapter._current_step_messages
