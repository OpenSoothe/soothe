"""IG-555 plan_assess guardrails for complex intake at iter=0."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.intention.models import TaskComplexity
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.intention import IntentClassification
from soothe.sloop.intention.models import IntakeLabel
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
    AgentDecision,
    LoopState,
    StatusAssessment,
    StepAction,
    StepExecutionRecord,
)


def _make_ctx(
    *,
    iteration: int = 0,
    intake_label: IntakeLabel = IntakeLabel.COMPLEX,
    current_decision: AgentDecision | None = None,
) -> LoopRuntimeContext:
    now = datetime.now(UTC)
    checkpoint = StrangeLoopCheckpoint(
        loop_id="loop-ig555",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="running",
        goal_history=[
            GoalIndexEntry(
                goal_id="g0",
                thread_id="tid",
                status="completed",
                started_at=now,
                completed_at=now,
            ),
            GoalIndexEntry(
                goal_id="g1",
                thread_id="tid",
                status="running",
                started_at=now,
            ),
        ],
        current_goal_index=1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=now),
        created_at=now,
        updated_at=now,
    )
    intent = IntentClassification(
        intake_label=intake_label,
        task_complexity=TaskComplexity.COMPLEX,
    )
    loop_state = LoopState(
        goal="build image then run e2e",
        thread_id="tid",
        iteration=iteration,
        continue_loop=True,
        intent=intent,
        current_decision=current_decision,
    )
    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(
            status="done",
            goal_progress="complete",
            assessment_reasoning="Anchored on prior completion.",
            require_goal_completion=False,
        )
    )
    strange_loop.config = MagicMock()
    strange_loop.config.agent.loop.goal_completion_mode = "llm_only"

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-ig555"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=checkpoint,
        goal_record=checkpoint.goal_history[-1],
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id="g1",
    )


def _one_step_decision() -> AgentDecision:
    return AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Apply prior recommendation")],
        execution_mode="parallel",
    )


def _two_step_decision() -> AgentDecision:
    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Build image"),
            StepAction(id="02", description="Run e2e"),
        ],
        execution_mode="dependency",
    )


@pytest.mark.asyncio
async def test_complex_iter0_rejects_complete_with_undersized_plan() -> None:
    ctx = _make_ctx(current_decision=_one_step_decision())
    result = await node_plan_assess(ctx, {})
    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_assessment.goal_progress == "medium"


@pytest.mark.asyncio
async def test_complex_iter0_rejects_complete_even_with_multi_step_plan() -> None:
    """Blanket anti-anchoring guard before any execution at iter=0."""
    ctx = _make_ctx(current_decision=_two_step_decision())
    result = await node_plan_assess(ctx, {})
    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_assessment.goal_progress == "medium"


@pytest.mark.asyncio
async def test_complex_iter1_allows_complete_with_single_step_replan() -> None:
    ctx = _make_ctx(iteration=1, current_decision=_one_step_decision())
    ctx.loop_state.step_results.append(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="tid")
    )
    ctx.strange_loop.plan_phase.finalize_plan_result = MagicMock(
        side_effect=lambda **kw: kw["result"]
    )
    ctx.plan_manager.determine_goal_completion_needs.return_value = False

    result = await node_plan_assess(ctx, {})
    assert result.get("plan_route") == "goal_done"


@pytest.mark.asyncio
async def test_simple_iter0_allows_complete_with_one_step() -> None:
    ctx = _make_ctx(intake_label=IntakeLabel.SIMPLE, current_decision=_one_step_decision())
    ctx.strange_loop.plan_phase.finalize_plan_result = MagicMock(
        side_effect=lambda **kw: kw["result"]
    )
    ctx.plan_manager.determine_goal_completion_needs.return_value = False

    result = await node_plan_assess(ctx, {})
    assert result.get("plan_route") == "goal_done"
