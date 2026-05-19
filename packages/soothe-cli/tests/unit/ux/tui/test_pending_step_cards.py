"""Pending step cards for planned-but-not-ready act steps."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    mark_parallel_plan_step_cards_running,
    sync_pending_step_cards_from_plan,
)


@pytest.mark.asyncio
async def test_plan_decision_mounts_pending_step_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
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
        request_approval=AsyncMock(),
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
async def test_parallel_plan_marks_all_pending_cards_running() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    steps = [
        {"id": "WAA-01", "description": "Step one"},
        {"id": "WAA-02", "description": "Step two"},
    ]
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=steps,
        execution_mode="parallel",
    )
    for sid in ("WAA-01", "WAA-02"):
        assert adapter._current_step_messages[sid]._status == "running"


@pytest.mark.asyncio
async def test_mark_parallel_plan_step_cards_running_only_pending() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "WAA-01", "description": "A"}],
    )
    card = adapter._current_step_messages["WAA-01"]
    card.set_running()
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "WAA-02", "description": "B"}],
    )
    mark_parallel_plan_step_cards_running(adapter)
    assert adapter._current_step_messages["WAA-01"]._status == "running"
    assert adapter._current_step_messages["WAA-02"]._status == "running"


@pytest.mark.asyncio
async def test_pending_card_transitions_to_running() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
        request_approval=AsyncMock(),
    )
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "WAA-01", "description": "Step one"}],
    )
    card = adapter._current_step_messages["WAA-01"]
    assert card._status == "pending"
    card.set_running()
    assert card._status == "running"
