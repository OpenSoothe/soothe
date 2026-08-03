"""Integration: mid-loop continuation planning coordinates intake with multi-step plans.

Exercises the orchestration spine for a loop-0b37-shaped follow-up: prior completed
goal, ``complex`` intake, evidence gather → plan_assess → plan_generate (no bootstrap).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.intention.models import TaskComplexity
from soothe_sdk.protocols.planner import PlanContext

from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.intention import IntentClassification
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.routing import (
    route_after_evidence_gather,
    route_by_intent,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.prompts.plan_ledger_projection import (
    _GOAL_COMPLETION_CONTEXT_BOUNDARY,
    project_planner_ledger,
    resolve_planner_projection_mode,
)
from soothe.sloop.stages.plan.assess import node_plan_assess
from soothe.sloop.stages.plan.gather_evidence import (
    node_bounded_evidence_gather,
)
from soothe.sloop.stages.plan.generate_plan import node_plan_generate
from soothe.sloop.stages.preprocess.enter_loop import node_init_or_resume
from soothe.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
)
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def _multi_step_plan_result() -> PlanResult:
    return PlanResult(
        status="continue",
        plan_action="new",
        decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="01",
                    description="Build airway Docker image",
                    full_description="Run make docker-build to produce the airway image.",
                    expected_output="Image built successfully",
                ),
                StepAction(
                    id="02",
                    description="Start docker components",
                    full_description="Start required docker-compose services for airway.",
                    expected_output="Containers healthy",
                ),
                StepAction(
                    id="03",
                    description="Run e2e test scripts",
                    full_description="Execute the airway e2e test suite against running stack.",
                    expected_output="E2E tests pass",
                ),
            ],
            execution_mode="dependency",
            reasoning="Decomposed docker build, startup, and verification.",
        ),
        next_action="I'll build the image, start services, then run e2e tests.",
        goal_progress="none",
    )


async def _noop_emit(_event_type: str, _event_data: object) -> None:
    return None


def _make_checkpoint(
    *,
    prior: GoalIndexEntry,
    active: GoalIndexEntry,
) -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    return StrangeLoopCheckpoint(
        loop_id="loop-cont",
        thread_ids=["tid"],
        current_thread_id="tid",
        status="running",
        goal_history=[prior, active],
        current_goal_index=1,
        working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
        thread_health_metrics=ThreadHealthMetrics(thread_id="tid", last_updated=now),
        created_at=now,
        updated_at=now,
    )


async def _make_continuation_context(
    *,
    goal: str,
) -> tuple[LoopRuntimeContext, AsyncMock]:
    """CE + checkpoint for a second goal in an existing loop."""
    now = datetime.now(UTC)
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="loop-cont", db_path=Path(":memory:"))
    )

    prior_goal = await ce.create_goal("upgrade soothe-client-go", loop_id="loop-cont")
    await ce.activate_goal(prior_goal.id, loop_id="loop-cont")
    await ce.complete_goal(prior_goal.id)

    active_goal = await ce.create_goal(goal, loop_id="loop-cont")
    await ce.activate_goal(active_goal.id, loop_id="loop-cont")

    prior_record = GoalIndexEntry(
        goal_id=prior_goal.id,
        thread_id="tid",
        status="completed",
        started_at=now,
        completed_at=now,
    )
    active_record = GoalIndexEntry(
        goal_id=active_goal.id,
        thread_id="tid",
        status="running",
        started_at=now,
    )
    checkpoint = _make_checkpoint(prior=prior_record, active=active_record)

    intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
        multi_phase=True,
    )
    loop_state = LoopState(
        goal=goal,
        thread_id="tid",
        iteration=0,
        continue_loop=True,
        intent=intent,
        loop_messages=[
            LoopHumanMessage(content="upgrade client", phase="intent_classify", thread_id="tid"),
            LoopAIMessage(
                content='{"intake_label":"simple"}',
                phase="intent_classify",
                thread_id="tid",
            ),
            LoopAIMessage(
                content="## Summary\nClient upgrade completed.",
                phase="goal_completion",
                thread_id="tid",
            ),
        ],
    )
    loop_state.bind_ce(ce, active_goal.id)

    assess_continuation = AsyncMock()
    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.loop_planner.assess_continuation = assess_continuation
    strange_loop.plan_phase.generate_from_assessment = AsyncMock(
        return_value=_multi_step_plan_result()
    )
    strange_loop.plan_phase.generate_lightweight = AsyncMock(
        side_effect=AssertionError("complex continuation must use full plan generate")
    )
    strange_loop.plan_phase.assess_status = AsyncMock(
        side_effect=AssertionError("continuation complex must skip continuation-assess LLM")
    )
    strange_loop.config = MagicMock()
    strange_loop.config.agent.loop.goal_completion_mode = "llm_only"

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-cont"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=checkpoint,
        goal_record=active_record,
        continue_loop_mode=True,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=_noop_emit,
        scratch=LoopPhaseScratch(),
        ce=ce,
        ce_goal_id=active_goal.id,
    )
    return ctx, assess_continuation


@pytest.mark.asyncio
async def test_continuation_complex_goal_produces_multi_step_plan() -> None:
    """Loop 0b37 goal_4 shape: complex continuation → full spine, multi-step plan, no bootstrap."""
    goal = (
        "run make docker-build to build airway image. "
        "then start docker components and run e2e test scripts"
    )
    ctx, assess_continuation = await _make_continuation_context(goal=goal)
    graph_state: dict[str, Any] = {}

    init_out = await node_init_or_resume(ctx, graph_state)
    graph_state.update(init_out)

    assert graph_state["is_continuation"] is True
    assert graph_state["is_fresh_goal"] is False
    assert graph_state["intake_label"] == IntakeLabel.COMPLEX
    assert ctx.scratch.plan_result is None

    route = route_by_intent(graph_state)
    assert route == "gather_evidence"

    evidence_out = await node_bounded_evidence_gather(ctx, graph_state)
    graph_state.update(evidence_out)
    assert route_after_evidence_gather(graph_state) == "evaluate"

    assess_out = await node_plan_assess(ctx, graph_state)
    graph_state.update(assess_out)
    assert assess_out.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_result is None
    assert ctx.scratch.plan_assessment is not None
    assess_continuation.assert_not_called()

    generate_out = await node_plan_generate(ctx, graph_state)
    graph_state.update(generate_out)

    plan_result = ctx.scratch.plan_result
    assert plan_result is not None
    assert plan_result.decision is not None
    assert len(plan_result.decision.steps) >= 1
    ctx.strange_loop.plan_phase.generate_from_assessment.assert_awaited_once()


@pytest.mark.asyncio
async def test_continuation_new_goal_projection_includes_boundary_marker() -> None:
    """IG-555: iter=0 continuation plan prompts include prior-goal boundary marker."""
    goal = "build image then run e2e"
    ctx, _ = await _make_continuation_context(goal=goal)
    # loop_messages is CE-backed once bound (see LoopState.loop_messages property),
    # so record into the CE ledger rather than assigning to the (ignored) cache.
    for msg in [
        LoopHumanMessage(content="finalize", phase="goal_completion", thread_id="tid"),
        LoopAIMessage(
            content="Recommended: apply signature change.",
            phase="goal_completion",
            thread_id="tid",
        ),
        LoopHumanMessage(content="GOAL: build", phase="intent_classify", thread_id="tid"),
        LoopAIMessage(
            content='{"intake_label":"complex"}', phase="intent_classify", thread_id="tid"
        ),
    ]:
        ctx.ce.ledger.record_message(msg, getattr(msg, "phase", ""))
    mode = resolve_planner_projection_mode(ctx.loop_state)
    projected = project_planner_ledger(
        ctx.loop_state.loop_messages,
        mode,
        None,
        soothe_config=ctx.strange_loop.config,
    )
    contents = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in contents


@pytest.mark.asyncio
async def test_continuation_trivial_git_commit_still_bootstraps() -> None:
    """Loop 0b37 goal_3 shape: trivial continuation may bootstrap (regression guard)."""
    now = datetime.now(UTC)
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="loop-triv", db_path=Path(":memory:"))
    )
    prior_goal = await ce.create_goal("fix gateway build", loop_id="loop-triv")
    await ce.activate_goal(prior_goal.id, loop_id="loop-triv")
    await ce.complete_goal(prior_goal.id)
    active_goal = await ce.create_goal("create git commit", loop_id="loop-triv")
    await ce.activate_goal(active_goal.id, loop_id="loop-triv")

    prior_record = GoalIndexEntry(
        goal_id=prior_goal.id,
        thread_id="tid",
        status="completed",
        started_at=now,
        completed_at=now,
    )
    active_record = GoalIndexEntry(
        goal_id=active_goal.id,
        thread_id="tid",
        status="running",
        started_at=now,
    )

    intent = IntentClassification(
        intake_label=IntakeLabel.TRIVIAL,
        task_complexity=TaskComplexity.MINIMAL,
    )
    loop_state = LoopState(
        goal="create git commit",
        thread_id="tid",
        iteration=0,
        continue_loop=True,
        intent=intent,
    )
    loop_state.bind_ce(ce, active_goal.id)

    continuation = MagicMock()
    continuation.action = "bootstrap"
    continuation.reasoning = "Single commit step from prior context."
    continuation.goal_progress = "low"

    assess_continuation = AsyncMock(return_value=continuation)
    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.loop_planner.assess_continuation = assess_continuation
    strange_loop.config = MagicMock()

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-triv"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=_make_checkpoint(prior=prior_record, active=active_record),
        goal_record=active_record,
        continue_loop_mode=True,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=_noop_emit,
        scratch=LoopPhaseScratch(),
        ce=ce,
        ce_goal_id=active_goal.id,
    )

    graph_state = {
        "is_continuation": True,
        "is_fresh_goal": False,
        "intake_label": IntakeLabel.TRIVIAL,
    }
    assert route_by_intent(graph_state) == "gather_evidence"

    assess_out = await node_plan_assess(ctx, graph_state)
    assert assess_out.get("assess_route") == "skip_generate"
    assert ctx.scratch.plan_result is not None
    assert len(ctx.scratch.plan_result.decision.steps) == 1
    assess_continuation.assert_awaited_once()


@pytest.mark.asyncio
async def test_continuation_simple_skips_assess_and_forces_generate() -> None:
    """Continuation+simple skips assess LLM and escalates to lightweight generate."""
    now = datetime.now(UTC)
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="loop-simple", db_path=Path(":memory:"))
    )
    prior_goal = await ce.create_goal("analyze prior failures", loop_id="loop-simple")
    await ce.activate_goal(prior_goal.id, loop_id="loop-simple")
    await ce.complete_goal(prior_goal.id)
    active_goal = await ce.create_goal("apply previous recommendation", loop_id="loop-simple")
    await ce.activate_goal(active_goal.id, loop_id="loop-simple")

    prior_record = GoalIndexEntry(
        goal_id=prior_goal.id,
        thread_id="tid",
        status="completed",
        started_at=now,
        completed_at=now,
    )
    active_record = GoalIndexEntry(
        goal_id=active_goal.id,
        thread_id="tid",
        status="running",
        started_at=now,
    )

    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    loop_state = LoopState(
        goal="apply previous recommendation",
        thread_id="tid",
        iteration=0,
        continue_loop=True,
        intent=intent,
    )
    loop_state.bind_ce(ce, active_goal.id)

    assess_continuation = AsyncMock(
        side_effect=AssertionError("simple continuation must skip assess_continuation LLM")
    )
    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.loop_planner.assess_continuation = assess_continuation
    strange_loop.config = MagicMock()

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-simple"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=_make_checkpoint(prior=prior_record, active=active_record),
        goal_record=active_record,
        continue_loop_mode=True,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=_noop_emit,
        scratch=LoopPhaseScratch(),
        ce=ce,
        ce_goal_id=active_goal.id,
    )

    graph_state = {
        "is_continuation": True,
        "is_fresh_goal": False,
        "intake_label": IntakeLabel.SIMPLE,
    }
    assert route_by_intent(graph_state) == "gather_evidence"

    assess_out = await node_plan_assess(ctx, graph_state)
    assert assess_out.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_assessment is not None
    assert ctx.scratch.plan_result is None
    assess_continuation.assert_not_awaited()
