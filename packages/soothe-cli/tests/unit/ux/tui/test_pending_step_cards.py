"""Pending step cards for planned-but-not-ready act steps."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    sync_pending_step_cards_from_plan,
)
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage


@pytest.mark.asyncio
async def test_plan_decision_mounts_pending_step_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    steps = [
        {"id": "WAA-01", "description": "Ready step"},
        {"id": "WAA-02", "description": "Blocked on WAA-01"},
    ]
    await sync_pending_step_cards_from_plan(adapter, steps=steps)

    assert set(adapter._current_step_messages) == {"WAA-01", "WAA-02"}
    for sid in ("WAA-01", "WAA-02"):
        card = adapter._current_step_messages[sid]
        assert card._status == "pending"


@pytest.mark.asyncio
async def test_plan_decision_replan_removes_stale_pending_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "OLD-01", "description": "Dropped"}],
    )
    mount = adapter._mount_message
    assert mount.await_count == 1

    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "NEW-01", "description": "Kept"}],
    )
    assert "OLD-01" not in adapter._current_step_messages
    assert "NEW-01" in adapter._current_step_messages
    assert mount.await_count == 2


@pytest.mark.asyncio
async def test_parallel_plan_keeps_pending_until_step_started() -> None:
    """Parallel plans must not promote every card to running before execute waves."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    steps = [
        {"id": "WAA-01", "description": "Step one"},
        {"id": "WAA-02", "description": "Step two"},
    ]
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=steps,
    )
    for sid in ("WAA-01", "WAA-02"):
        assert adapter._current_step_messages[sid]._status == "pending"


@pytest.mark.asyncio
async def test_queued_card_shows_queued_status() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "WAA-01", "description": "Step one"}],
    )
    card = adapter._current_step_messages["WAA-01"]
    card.set_queued()
    assert card._status == "queued"


@pytest.mark.asyncio
async def test_pending_card_transitions_to_running() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "WAA-01", "description": "Step one"}],
    )
    card = adapter._current_step_messages["WAA-01"]
    assert card._status == "pending"
    card.set_running()
    assert card._status == "running"


def test_future_step_stays_pending_when_sibling_is_running() -> None:
    """RFC-628: pre-mounted steps must not flip to running from tool ingest alone."""
    from soothe_cli.runtime.state.step_router import StepTaskRouter

    router = StepTaskRouter()
    active = CognitionStepMessage("WAA-01", "Step one", id="step-one")
    active.set_running()
    future = CognitionStepMessage("WAA-02", "Step two", id="step-two")
    step_cards = {"WAA-01": active, "WAA-02": future}

    future.add_tool_call("WAA_02:s:grep:0", "grep", {"pattern": "x"})
    router.maybe_promote_step_to_running(
        future,
        "WAA_02:s:grep:0",
        step_cards=step_cards,
    )

    assert active._status == "running"
    assert future._status == "pending"


def test_active_step_promotes_before_step_started_event() -> None:
    """Tools may arrive before step.started; the active step may show running early."""
    from soothe_cli.runtime.state.step_router import StepTaskRouter

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
