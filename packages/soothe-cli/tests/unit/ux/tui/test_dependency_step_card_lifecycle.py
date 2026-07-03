"""Dependency-mode step card lifecycle (RFC-628 / stuck predecessor safety net)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _finalize_stuck_dependency_predecessors,
    _lookup_step_card,
    _pop_step_card_from_adapter,
    sync_pending_step_cards_from_plan,
)
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage


def test_lookup_step_card_finds_wire_key_alias() -> None:
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    card = CognitionStepMessage("THQ-01", "Review", id="step-one")
    adapter._current_step_messages["THQ_01"] = card

    key, found = _lookup_step_card(adapter, "THQ-01")
    assert key == "THQ_01"
    assert found is card


def test_pop_step_card_removes_alias_keys() -> None:
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    card = CognitionStepMessage("THQ-01", "Review", id="step-one")
    adapter._current_step_messages["THQ-01"] = card
    adapter._current_step_messages["THQ_01"] = card

    popped = _pop_step_card_from_adapter(adapter, "THQ-01")
    assert popped is card
    assert adapter._current_step_messages == {}


def test_finalize_stuck_dependency_predecessor_on_step_two_start() -> None:
    """When step 2 starts in dependency mode, step 1 must not stay running in the UI."""
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "dependency"
    router = StepTaskRouter()

    step_one = CognitionStepMessage("THQ-01", "Review RFC gaps", id="step-one")
    step_one.set_running()
    step_two = CognitionStepMessage("THQ-02", "Implement gaps", id="step-two")
    adapter._current_step_messages["THQ-01"] = step_one
    adapter._current_step_messages["THQ-02"] = step_two
    router.on_step_started("THQ-01")

    _finalize_stuck_dependency_predecessors(
        adapter,
        router,
        next_step_id="THQ-02",
        ns_key=(),
    )

    assert step_one._status == "success"
    assert step_two._status == "pending"
    assert "THQ-01" not in adapter._current_step_messages
    assert "THQ-02" in adapter._current_step_messages
    assert "THQ-01" not in router.active_step_ids


def test_finalize_stuck_skipped_in_parallel_mode() -> None:
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "parallel"
    router = StepTaskRouter()

    step_one = CognitionStepMessage("WAA-01", "First", id="step-one")
    step_one.set_running()
    adapter._current_step_messages["WAA-01"] = step_one
    router.on_step_started("WAA-01")

    _finalize_stuck_dependency_predecessors(
        adapter,
        router,
        next_step_id="WAA-02",
        ns_key=(),
    )

    assert step_one._status == "running"
    assert "WAA-01" in router.active_step_ids


@pytest.mark.asyncio
async def test_plan_decision_then_dependency_unlock_sequence() -> None:
    """Pending step 2 stays pending until step 1 completes and step 2 starts."""
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "dependency"
    steps = [
        {"id": "THQ-01", "description": "Review"},
        {"id": "THQ-02", "description": "Implement"},
    ]
    await sync_pending_step_cards_from_plan(adapter, steps=steps)
    assert adapter._current_step_messages["THQ-01"]._status == "pending"
    assert adapter._current_step_messages["THQ-02"]._status == "pending"

    adapter._current_step_messages["THQ-01"].set_running()
    assert adapter._current_step_messages["THQ-02"]._status == "pending"

    popped = _pop_step_card_from_adapter(adapter, "THQ-01")
    assert popped is not None
    popped.set_complete(True, 1000, 2, "Done")
    assert popped._status == "success"

    adapter._current_step_messages["THQ-02"].set_running()
    assert adapter._current_step_messages["THQ-02"]._status == "running"
