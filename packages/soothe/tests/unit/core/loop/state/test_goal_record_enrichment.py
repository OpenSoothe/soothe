"""Tests for RFC-225 GoalExecutionRecord enrichment round-trip.

Verifies that ``current_plan``, ``completed_step_ids``, ``step_results``,
``evidence_ledger``, and ``plan_revision_count`` persist and restore
through the SQLite manager's ``goal_records`` table (via the
``extras_jsonb`` column added by IG-445).
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.foundation.loop.state.checkpoint import GoalExecutionRecord
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    EvidenceEntry,
    PlanResult,
    StepAction,
    StepResult,
)
from soothe.foundation.loop.state.sloop_manager import StrangeLoopStateManager


@pytest.fixture
def temp_state_manager():
    """Create a temp-scoped StrangeLoopStateManager (mirrors test_checkpoint_index_fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_loop_checkpoints.db"
        with patch(
            "soothe.foundation.loop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            yield StrangeLoopStateManager(loop_id="ig445_loop_001", workspace=workspace)


def _make_plan() -> PlanResult:
    s1 = StepAction(id="s1", description="step one", expected_output="ok")
    s2 = StepAction(id="s2", description="step two", expected_output="ok", dependencies=["s1"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[s1, s2],
        execution_mode="dependency",
        reasoning="two-step plan",
    )
    return PlanResult(
        status="continue",
        plan_action="new",
        decision=decision,
        goal_progress="low",
        next_action="Execute s1, then s2",
    )


@pytest.mark.asyncio
async def test_goal_record_round_trip_through_sqlite(temp_state_manager) -> None:
    sm = temp_state_manager
    checkpoint = await sm.initialize("thread_001", max_iterations=8)

    # Append + persist a goal with enrichment populated.
    goal = sm.start_new_goal("verify round-trip", max_iterations=8)
    checkpoint.goal_history.append(goal)
    checkpoint.current_goal_index = 0
    checkpoint.status = "running"

    plan = _make_plan()
    sr1 = StepResult(
        step_id="s1",
        success=True,
        outcome={"type": "text"},
        duration_ms=100,
        thread_id="thread_001",
    )
    sr2 = StepResult(
        step_id="s2",
        success=True,
        outcome={"type": "text"},
        duration_ms=200,
        thread_id="thread_001",
    )
    ev = EvidenceEntry(evidence_id="e1", summary="s1 completed", kind="tool")

    goal.current_plan = plan
    goal.completed_step_ids = {"s1", "s2"}
    goal.plan_revision_count = 3
    goal.step_results = [sr1, sr2]
    goal.evidence_ledger = [ev]
    goal.status = "completed"
    goal.completed_at = datetime.now(UTC)
    goal.goal_completion = "done"
    goal.evidence_summary = "all steps succeeded"
    checkpoint.status = "idle"

    await sm.save(checkpoint)

    # Cold load via fresh manager pointing at the same DB.
    with patch(
        "soothe.foundation.loop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
        return_value=sm.db_path,
    ):
        sm2 = StrangeLoopStateManager(loop_id=sm.loop_id, workspace=Path(sm.db_path).parent)
        loaded = await sm2.load()

    assert loaded is not None
    assert loaded.status == "idle"
    assert len(loaded.goal_history) == 1
    g: GoalExecutionRecord = loaded.goal_history[0]

    # Identity preserved
    assert g.goal_id == goal.goal_id
    assert g.max_iterations == 8

    # RFC-225 enrichment round-tripped
    assert g.current_plan is not None
    assert g.current_plan.decision is not None
    assert [s.id for s in g.current_plan.decision.steps] == ["s1", "s2"]
    assert g.current_plan.decision.steps[1].dependencies == ["s1"]
    assert g.current_plan.decision.execution_mode == "dependency"

    assert g.completed_step_ids == {"s1", "s2"}
    assert g.plan_revision_count == 3
    assert {r.step_id for r in g.step_results} == {"s1", "s2"}
    assert len(g.evidence_ledger) == 1
    assert g.evidence_ledger[0].evidence_id == "e1"
