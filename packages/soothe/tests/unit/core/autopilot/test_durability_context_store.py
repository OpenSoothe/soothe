"""Tests for DurabilityGoalDispatchContextStore."""

from __future__ import annotations

import pytest

from soothe.backends.persistence.sqlite_store import SQLitePersistStore
from soothe.foundation.autopilot.service.durability_context_store import DurabilityGoalDispatchContextStore
from soothe.foundation.autopilot.engine.models import GoalDispatchContextContribution


@pytest.mark.asyncio
async def test_round_trip(tmp_path) -> None:
    store = DurabilityGoalDispatchContextStore(
        SQLitePersistStore(db_path=str(tmp_path / "t.db"), namespace="autopilot_ctx")
    )
    contrib = GoalDispatchContextContribution()
    await store.put("goal-1", contrib)
    loaded = await store.get("goal-1")
    assert loaded is not None
    assert await store.all_goal_ids() == {"goal-1"}
    assert await store.delete("goal-1") is True
    assert await store.get("goal-1") is None
