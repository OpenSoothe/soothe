"""Tests for RFC-225/RFC-226 loop-continuation plan_assess paths.

Covers:
- ``build_continue_loop_bootstrap_plan`` shape + terminal_after_execute flag (RFC-226).
- ``_prior_goal_summaries`` reads from CE GoalStepDAG (RFC-624 Phase 4 Stage 2).

RFC-624 Phase 4 Stage 2: seed_loop_ledger_from_prior_goal deleted.
CE ledger spans all goals via ce.load(), no explicit seeding needed.
"""

from datetime import UTC, datetime
from pathlib import Path

from soothe.foundation.sloop.orchestrator.nodes.plan_assess import (
    _prior_goal_summaries,
    build_continue_loop_bootstrap_plan,
)
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.sloop.state.schemas import LoopState

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence


def _make_ce_with_completed_goal() -> ContextEngine:
    """Create a CE instance with a completed goal for testing."""
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    goal = GoalNode(description="count files", status="completed")
    goal.action_history.append("There are 3 README files.")
    ce._dag.add_goal(goal)
    return ce


def _make_runtime_context_with_ce(ce: ContextEngine) -> LoopRuntimeContext:
    """Create a LoopRuntimeContext bound to a CE instance."""
    state = LoopState(goal="test", thread_id="tid")
    state.bind_ce(ce, "goal-0")
    checkpoint = StrangeLoopCheckpoint(
        loop_id="loop-x",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="idle",
        goal_history=[],
        current_goal_index=-1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=datetime.now(UTC)),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return LoopRuntimeContext(
        strange_loop=None,
        state_manager=None,  # not needed for this test
        anchor_manager=None,
        goal_context_manager=None,
        plan_manager=None,
        goal_record=None,
        recovery_valid_resume=False,
        emit=_noop_emit,
        loop_state=state,
        checkpoint=checkpoint,
        scratch=LoopPhaseScratch(),
        continue_loop_mode=True,
        ce=ce,
    )


async def _noop_emit(_event_type: str, _event_data: object) -> None:
    return None


# ── build_continue_loop_bootstrap_plan ─────────────────────────────────────


def test_build_bootstrap_plan_shape() -> None:
    pr = build_continue_loop_bootstrap_plan("user follow-up")
    assert pr.status == "continue"
    assert pr.plan_action == "new"
    assert pr.decision is not None
    assert pr.decision.type == "execute_steps"
    assert len(pr.decision.steps) == 1
    assert pr.decision.execution_mode == "parallel"
    # RFC-226 default: not terminal
    assert pr.terminal_after_execute is False


def test_build_bootstrap_plan_terminal_flag_propagates() -> None:
    pr = build_continue_loop_bootstrap_plan(
        "translate the result to chinese",
        terminal_after_execute=True,
        reasoning="Pure translation; no new tools needed.",
        goal_progress="low",
    )
    assert pr.terminal_after_execute is True
    assert pr.assessment_reasoning == "Pure translation; no new tools needed."
    assert pr.goal_progress == "low"
    # Step description embeds the actual goal text.
    assert "translate the result to chinese" in pr.decision.steps[0].description


# ── _prior_goal_summaries (RFC-226, RFC-624 Phase 4 Stage 2) ───────────────────


def test_prior_goal_summaries_reads_ce_dag() -> None:
    """Stage 2: _prior_goal_summaries reads from CE GoalStepDAG, not checkpoint."""
    ce = _make_ce_with_completed_goal()
    ctx = _make_runtime_context_with_ce(ce)
    summaries = _prior_goal_summaries(ctx)
    assert len(summaries) == 1
    assert summaries[0]["goal_text"] == "count files"
    assert "README" in summaries[0]["completion"]


def test_prior_goal_summaries_empty_without_ce() -> None:
    """When CE is None, returns empty list (tests without CE)."""
    checkpoint = StrangeLoopCheckpoint(
        loop_id="loop-x",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="idle",
        goal_history=[],
        current_goal_index=-1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=datetime.now(UTC)),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    state = LoopState(goal="test", thread_id="tid")
    ctx = LoopRuntimeContext(
        strange_loop=None,
        state_manager=None,
        anchor_manager=None,
        goal_context_manager=None,
        plan_manager=None,
        goal_record=None,
        recovery_valid_resume=False,
        emit=_noop_emit,
        loop_state=state,
        checkpoint=checkpoint,
        scratch=LoopPhaseScratch(),
        continue_loop_mode=False,
    )
    summaries = _prior_goal_summaries(ctx)
    assert summaries == []
