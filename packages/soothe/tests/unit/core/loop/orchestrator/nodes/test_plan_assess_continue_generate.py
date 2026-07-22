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

from soothe.sloop.nodes.plan_assess import node_plan_assess
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.state.schemas import (
    ContinuationAssessment,
    LoopState,
    StatusAssessment,
)


def _make_prior_goal() -> GoalIndexEntry:
    now = datetime.now(UTC)
    return GoalIndexEntry(
        goal_id="g0",
        thread_id="tid",
        status="completed",
        started_at=now,
        completed_at=now,
    )


def _make_active_goal(goal: str = "fix to add trace metadata") -> GoalIndexEntry:
    now = datetime.now(UTC)
    _ = goal
    return GoalIndexEntry(
        goal_id="g1",
        thread_id="tid",
        status="running",
        started_at=now,
    )


def _make_checkpoint(
    prior: GoalIndexEntry,
    active: GoalIndexEntry,
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
    strange_loop.loop_planner.assess_continuation = AsyncMock()
    # Non-continuation assess path is not under test in this file.
    strange_loop.plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(status="continue", goal_progress="low")
    )

    completed_goal = MagicMock()
    completed_goal.id = "goal-0"
    completed_goal.description = "analyze trace data"
    completed_goal.status = "completed"
    completed_goal.action_history = ["Trace analysis complete."]
    completed_goal.steps = MagicMock()
    completed_goal.steps.nodes = {}

    ce = MagicMock()
    ce.get_all_goals.return_value = [completed_goal]
    ce.ledger = MagicMock()
    ce.ledger.get_messages.return_value = []

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
        ce=ce,
        ce_goal_id="goal-active",
    )


@pytest.mark.asyncio
async def test_continue_keyword_bootstrap_without_assess_continuation() -> None:
    """Lone ``continue`` bootstraps deterministically without continuation-assess LLM."""
    ctx = _make_ctx(goal="continue")
    cancelled_goal = MagicMock()
    cancelled_goal.id = "goal-0"
    cancelled_goal.description = "review all local changes"
    cancelled_goal.status = "cancelled"
    cancelled_goal.action_history = []
    cancelled_goal.steps = MagicMock()
    cancelled_goal.steps.nodes = {"s1": MagicMock(status="completed")}
    ctx.ce.get_all_goals.return_value = [cancelled_goal]

    result = await node_plan_assess(ctx, {})

    assert result.get("assess_route") == "skip_generate"
    ctx.strange_loop.loop_planner.assess_continuation.assert_not_called()
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_assessment is None
    step = ctx.scratch.plan_result.decision.steps[0]
    assert step.description == "Continue prior goal completion recommendations"
    assert ctx.scratch.plan_result.terminal_after_execute is True


@pytest.mark.asyncio
async def test_continue_keyword_respects_assess_plan_generate() -> None:
    """Continue keyword always bootstraps; plan_generate requires a specific follow-up goal."""
    ctx = _make_ctx(goal="continue")
    completion_body = (
        "## Recommendations\nHigh priority: implement continuation envelope grounding."
    )
    completed_goal = MagicMock()
    completed_goal.id = "goal-0"
    completed_goal.description = "analyze trace data"
    completed_goal.status = "completed"
    completed_goal.action_history = [completion_body]
    completed_goal.steps = MagicMock()
    completed_goal.steps.nodes = {"s1": MagicMock(status="completed")}
    ctx.ce.get_all_goals.return_value = [completed_goal]

    result = await node_plan_assess(ctx, {})

    assert result.get("assess_route") == "skip_generate"
    ctx.strange_loop.loop_planner.assess_continuation.assert_not_called()
    assert ctx.scratch.plan_result is not None


@pytest.mark.asyncio
async def test_continue_keyword_plan_event_omits_duplicate_reason_display() -> None:
    """Continue keyword bootstrap suppresses boilerplate on the plan wire event."""
    emitted: list[tuple[str, dict[str, object]]] = []
    ctx = _make_ctx(goal="continue")

    cancelled_goal = MagicMock()
    cancelled_goal.id = "goal-0"
    cancelled_goal.description = "review all local changes"
    cancelled_goal.status = "cancelled"
    cancelled_goal.action_history = []
    cancelled_goal.steps = MagicMock()
    cancelled_goal.steps.nodes = {"s1": MagicMock(status="completed")}

    ctx.ce.get_all_goals.return_value = [cancelled_goal]

    async def emit(event_type: str, event_data: object) -> None:
        if isinstance(event_data, dict):
            emitted.append((event_type, event_data))

    ctx.emit = emit  # type: ignore[method-assign]

    await node_plan_assess(ctx, {})

    plan_events = [d for t, d in emitted if t == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["assessment_reasoning"] == ""
    assert plan_events[0]["plan_reasoning"] == ""
    assert plan_events[0]["next_action"] == ""
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_result.assessment_reasoning == ""


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
    assert len([t for t, _ in emitted if t == "plan_phase_status"]) == 1
    plan_events = [d for t, d in emitted if t == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["assessment_reasoning"] == "Pure translation; no new tools needed."
    assert plan_events[0]["plan_reasoning"]


@pytest.mark.asyncio
async def test_continuation_complex_intake_skips_bootstrap() -> None:
    """Complex intake on continuation must not bootstrap (loop 0b37 goal_4 shape)."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention import IntentClassification
    from soothe.sloop.intention.models import IntakeLabel

    goal = (
        "run make docker-build to build airway image. "
        "then start docker components and run e2e test scripts"
    )
    ctx = _make_ctx(goal=goal)
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )

    result = await node_plan_assess(ctx, {})

    assert result.get("assess_route") == "continue_generate"
    ctx.strange_loop.loop_planner.assess_continuation.assert_not_called()
    assert ctx.scratch.plan_assessment is not None
    assert ctx.scratch.plan_result is None
