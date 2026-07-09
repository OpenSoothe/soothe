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
    cleanup_stale_plan_step_cards,
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
    adapter._plan_step_order = ["THQ-01", "THQ-02"]
    adapter._plan_step_ids = {"THQ-01", "THQ-02"}
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


def test_finalize_stuck_skips_sibling_parallel_steps() -> None:
    """Sibling steps in one dependency wave must not force-complete each other."""
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "dependency"
    adapter._plan_step_order = ["AAV-03", "AAV-04"]
    adapter._plan_step_ids = {"AAV-03", "AAV-04"}
    adapter._plan_step_dependencies = {
        "AAV-03": ("FKB-01", "FKB-02"),
        "AAV-04": ("FKB-01", "FKB-02"),
    }
    router = StepTaskRouter()

    step_three = CognitionStepMessage("AAV-03", "Fix cross-ref conflicts", id="step-three")
    step_three.set_running()
    step_four = CognitionStepMessage("AAV-04", "Fix protocols pages", id="step-four")
    adapter._current_step_messages["AAV-03"] = step_three
    adapter._current_step_messages["AAV-04"] = step_four
    router.on_step_started("AAV-03")

    _finalize_stuck_dependency_predecessors(
        adapter,
        router,
        next_step_id="AAV-04",
        ns_key=(),
    )

    assert step_three._status == "running"
    assert "AAV-03" in adapter._current_step_messages
    assert "AAV-03" in router.active_step_ids


def test_finalize_stuck_honors_explicit_in_plan_dependency() -> None:
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "dependency"
    adapter._plan_step_order = ["THQ-01", "THQ-02"]
    adapter._plan_step_ids = {"THQ-01", "THQ-02"}
    adapter._plan_step_dependencies = {"THQ-02": ("THQ-01",)}
    router = StepTaskRouter()

    step_one = CognitionStepMessage("THQ-01", "Review", id="step-one")
    step_one.set_running()
    step_two = CognitionStepMessage("THQ-02", "Implement", id="step-two")
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
    assert "THQ-01" not in adapter._current_step_messages


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
    """Step 2 card mounts only when it starts running; plan view tracks both steps."""
    adapter = TextualUIAdapter(mount_message=AsyncMock(), update_status=AsyncMock())
    adapter._last_plan_execution_mode = "dependency"
    steps = [
        {"id": "THQ-01", "description": "Review"},
        {"id": "THQ-02", "description": "Implement"},
    ]
    await cleanup_stale_plan_step_cards(adapter, steps=steps)
    assert adapter._current_step_messages == {}

    step_one = CognitionStepMessage("THQ-01", "Review", id="step-one")
    await adapter._mount_message(step_one)
    adapter._current_step_messages["THQ-01"] = step_one
    step_one.set_running()
    assert step_one._status == "running"

    popped = _pop_step_card_from_adapter(adapter, "THQ-01")
    assert popped is not None
    popped.set_complete(True, 1000, 2, "Done")
    assert popped._status == "success"

    step_two = CognitionStepMessage("THQ-02", "Implement", id="step-two")
    await adapter._mount_message(step_two)
    adapter._current_step_messages["THQ-02"] = step_two
    step_two.set_running()
    assert step_two._status == "running"
