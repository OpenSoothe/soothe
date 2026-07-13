"""IG-557 mid-goal execution-evidence guard for plan_assess."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.orchestrator.nodes.plan_assess import node_plan_assess
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StatusAssessment,
    StepAction,
    StepResult,
)
from soothe.protocols.planner import PlanContext


def _make_ctx(
    *,
    iteration: int = 1,
    intake_label: IntakeLabel = IntakeLabel.COMPLEX,
    current_decision: AgentDecision | None = None,
    step_results: list[StepResult] | None = None,
    loop_messages: list | None = None,
) -> LoopRuntimeContext:
    now = datetime.now(UTC)
    checkpoint = StrangeLoopCheckpoint(
        loop_id="loop-ig557",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="running",
        goal_history=[
            GoalIndexEntry(
                goal_id="g1",
                thread_id="tid",
                status="running",
                started_at=now,
            ),
        ],
        current_goal_index=0,
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
        intent=intent,
        current_decision=current_decision,
        loop_messages=loop_messages or [],
    )
    if step_results:
        loop_state.step_results.extend(step_results)

    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(
            status="done",
            goal_progress="complete",
            assessment_reasoning="Premature complete.",
            require_goal_completion=False,
        )
    )
    strange_loop.config = MagicMock()
    strange_loop.config.agent.loop.goal_completion_mode = "llm_only"
    strange_loop.plan_phase.finalize_plan_result = MagicMock(side_effect=lambda **kw: kw["result"])

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-ig557"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(determine_goal_completion_needs=MagicMock(return_value=False)),
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
async def test_complex_mid_goal_rejects_complete_without_execution() -> None:
    ctx = _make_ctx(iteration=1, current_decision=_two_step_decision())
    result = await node_plan_assess(ctx, {})
    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_assessment.goal_progress == "medium"


@pytest.mark.asyncio
async def test_complex_mid_goal_rejects_complete_with_remaining_plan_steps() -> None:
    ctx = _make_ctx(
        iteration=1,
        current_decision=_two_step_decision(),
        step_results=[
            StepResult(step_id="01", success=True, duration_ms=1, thread_id="tid"),
        ],
    )
    result = await node_plan_assess(ctx, {})
    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_assessment.goal_progress == "medium"


@pytest.mark.asyncio
async def test_complex_mid_goal_allows_complete_when_plan_exhausted() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Build image")],
        execution_mode="parallel",
    )
    ctx = _make_ctx(
        iteration=1,
        current_decision=decision,
        step_results=[
            StepResult(step_id="01", success=True, duration_ms=1, thread_id="tid"),
        ],
    )
    result = await node_plan_assess(ctx, {})
    assert result.get("plan_route") == "goal_done"


@pytest.mark.asyncio
async def test_simple_mid_goal_allows_complete_with_evidence() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Do one thing")],
        execution_mode="parallel",
    )
    ctx = _make_ctx(
        iteration=1,
        intake_label=IntakeLabel.SIMPLE,
        current_decision=decision,
        step_results=[
            StepResult(step_id="01", success=True, duration_ms=1, thread_id="tid"),
        ],
    )
    result = await node_plan_assess(ctx, {})
    assert result.get("plan_route") == "goal_done"
