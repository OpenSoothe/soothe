"""Tests for the plan_generate continuation path in node_plan_assess (RFC-226).

Verifies that when continuation-assess routes to plan_generate, it constructs a
StatusAssessment on scratch instead of clearing it to None — preventing the
cascading fatal error where plan_generate finds no assessment payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.loop.orchestrator.nodes.plan_assess import node_plan_assess
from soothe.foundation.loop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.loop.state.checkpoint import (
    GoalExecutionRecord,
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.loop.state.schemas import (
    ContinuationAssessment,
    LoopState,
    StatusAssessment,
)


def _make_prior_goal() -> GoalExecutionRecord:
    now = datetime.now(UTC)
    return GoalExecutionRecord(
        goal_id="g0",
        goal_text="analyze trace data",
        thread_id="tid",
        status="completed",
        goal_completion="Trace analysis complete.",
        loop_messages=[],
        started_at=now,
        completed_at=now,
    )


def _make_active_goal(goal: str = "fix to add trace metadata") -> GoalExecutionRecord:
    now = datetime.now(UTC)
    return GoalExecutionRecord(
        goal_id="g1",
        goal_text=goal,
        thread_id="tid",
        status="running",
        loop_messages=[],
        started_at=now,
        iteration=0,
    )


def _make_checkpoint(
    prior: GoalExecutionRecord,
    active: GoalExecutionRecord,
) -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    return StrangeLoopCheckpoint(
        loop_id="loop-test",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="idle",
        goal_history=[prior, active],
        current_goal_index=-1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=now),
        created_at=now,
        updated_at=now,
    )


def _make_ctx(
    *,
    goal: str = "fix to add trace metadata",
    continue_loop: bool = True,
) -> LoopRuntimeContext:
    prior = _make_prior_goal()
    active = _make_active_goal(goal)
    checkpoint = _make_checkpoint(prior, active)

    loop_state = LoopState(
        iteration=0,
        goal=goal,
        thread_id="tid",
    )

    strange_loop = MagicMock()
    strange_loop._build_plan_context = MagicMock(
        return_value=MagicMock(available_capabilities=["read_file", "run_python"]),
    )

    emitted: list[tuple[str, Any]] = []

    async def emit(event_type: str, event_data: Any) -> None:
        emitted.append((event_type, event_data))

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-test"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=checkpoint,
        goal_record=active,
        continue_loop_mode=continue_loop,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=emit,
        scratch=LoopPhaseScratch(),
    )


@pytest.mark.asyncio
async def test_continuation_plan_generate_sets_status_assessment() -> None:
    """When continuation-assess decides plan_generate, scratch gets a StatusAssessment."""
    ctx = _make_ctx(goal="fix to add trace metadata")
    continuation = ContinuationAssessment(
        action="plan_generate",
        reasoning="Requires code modifications across multiple files.",
        goal_progress="none",
    )

    strange_loop = ctx.strange_loop
    strange_loop.loop_planner.assess_continuation = AsyncMock(return_value=continuation)

    result = await node_plan_assess(ctx, {})

    # Routes to plan_generate (not skip_generate or goal_done).
    assert result.get("assess_route") == "continue_generate"
    # The critical fix: scratch.plan_assessment is a StatusAssessment, not None.
    assert ctx.scratch.plan_assessment is not None
    assert isinstance(ctx.scratch.plan_assessment, StatusAssessment)
    assert ctx.scratch.plan_assessment.status == "continue"
    assert ctx.scratch.plan_assessment.goal_progress == "none"
    assert "code modifications" in ctx.scratch.plan_assessment.assessment_reasoning
    assert ctx.scratch.plan_assessment.require_goal_completion is False


@pytest.mark.asyncio
async def test_continuation_bootstrap_still_sets_plan_result() -> None:
    """Bootstrap path still sets plan_result and clears plan_assessment (unchanged)."""
    ctx = _make_ctx(goal="translate the result to chinese")
    continuation = ContinuationAssessment(
        action="bootstrap",
        reasoning="Pure translation; no new tools needed.",
        goal_progress="low",
    )

    strange_loop = ctx.strange_loop
    strange_loop.loop_planner.assess_continuation = AsyncMock(return_value=continuation)

    result = await node_plan_assess(ctx, {})

    assert result.get("assess_route") == "skip_generate"
    assert ctx.scratch.plan_assessment is None
    assert ctx.scratch.plan_result is not None


@pytest.mark.asyncio
async def test_continuation_bootstrap_emits_single_combined_reason_card() -> None:
    """Bootstrap surfaces reasoning only on the plan event (no duplicate assess card)."""
    emitted: list[tuple[str, dict[str, object]]] = []
    ctx = _make_ctx(goal="translate the result to chinese")
    continuation = ContinuationAssessment(
        action="bootstrap",
        reasoning="Pure translation; no new tools needed.",
        goal_progress="low",
    )
    ctx.strange_loop.loop_planner.assess_continuation = AsyncMock(return_value=continuation)

    async def emit(event_type: str, event_data: object) -> None:
        if isinstance(event_data, dict):
            emitted.append((event_type, event_data))

    ctx.emit = emit  # type: ignore[method-assign]

    await node_plan_assess(ctx, {})

    assert [t for t, _ in emitted if t == "assess"] == []
    plan_events = [d for t, d in emitted if t == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["assessment_reasoning"] == "Pure translation; no new tools needed."
    assert plan_events[0]["plan_reasoning"]
