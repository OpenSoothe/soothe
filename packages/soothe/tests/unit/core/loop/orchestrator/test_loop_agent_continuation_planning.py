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
from soothe_sdk.protocols.planner import PlanContext

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.orchestrator.nodes.bounded_evidence_gather import (
    node_bounded_evidence_gather,
)
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume
from soothe.foundation.sloop.orchestrator.nodes.plan_assess import node_plan_assess
from soothe.foundation.sloop.orchestrator.nodes.plan_generate import node_plan_generate
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.routing import (
    route_after_evidence_gather,
    route_after_plan,
    route_by_intent,
)
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
    PlanResult,
    StepAction,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.prompts.plan_ledger_projection import (
    _GOAL_COMPLETION_CONTEXT_BOUNDARY,
    project_planner_ledger,
    resolve_planner_projection_mode,
)


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
        plan_reasoning="Three-phase operational goal.",
        goal_progress="none",
    )


def _one_step_plan_result() -> PlanResult:
    return PlanResult(
        status="continue",
        plan_action="new",
        decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="01",
                    description="Apply prior recommendation",
                    full_description="Execute recommended next action from prior goal.",
                    expected_output="Change applied",
                ),
            ],
            execution_mode="parallel",
            reasoning="Anchored on prior completion report.",
        ),
        next_action="Apply the recommended change.",
        plan_reasoning="Single step from prior report.",
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
    """Loop 0b37 goal_4 shape: complex continuation → full spine, ≥2 steps, no bootstrap."""
    goal = (
        "run make docker-build to build airway image. "
        "then start docker components and run e2e test scripts"
    )
    ctx, assess_continuation = await _make_continuation_context(goal=goal)
    graph_state: dict[str, Any] = {}

    init_out = await node_init_or_resume(ctx, graph_state)
    graph_state.update(init_out)

    assert graph_state["is_continuation"] is True
    assert graph_state["intake_label"] == IntakeLabel.COMPLEX
    assert ctx.scratch.plan_result is None

    route = route_by_intent(graph_state)
    assert route == "bounded_evidence_gather"

    evidence_out = await node_bounded_evidence_gather(ctx, graph_state)
    graph_state.update(evidence_out)
    assert route_after_evidence_gather(graph_state) == "plan_assess"

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
    assert len(plan_result.decision.steps) >= 2
    ctx.strange_loop.plan_phase.generate_from_assessment.assert_awaited_once()


@pytest.mark.asyncio
async def test_continuation_complex_goal_replans_undersized_plan() -> None:
    """IG-555: 1-step generate loops via route_after_plan until a multi-step plan is produced."""
    goal = "build image then start components and run e2e"
    ctx, _assess_continuation = await _make_continuation_context(goal=goal)
    ctx.strange_loop.plan_phase.generate_from_assessment = AsyncMock(
        side_effect=[_one_step_plan_result(), _multi_step_plan_result()]
    )

    graph_state: dict[str, Any] = {}
    await node_init_or_resume(ctx, graph_state)
    await node_bounded_evidence_gather(ctx, graph_state)
    assess_out = await node_plan_assess(ctx, graph_state)
    graph_state.update(assess_out)

    first_generate = await node_plan_generate(ctx, graph_state)
    graph_state.update(first_generate)
    assert first_generate.get("assess_route") == "continue_generate"
    assert route_after_plan(graph_state) == "plan_generate"

    second_generate = await node_plan_generate(ctx, graph_state)
    graph_state.update(second_generate)
    assert second_generate.get("plan_route") == "execute"
    assert second_generate.get("assess_route") is None
    assert len(ctx.scratch.plan_result.decision.steps) >= 2
    assert ctx.strange_loop.plan_phase.generate_from_assessment.await_count == 2


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
        "intake_label": IntakeLabel.TRIVIAL,
    }
    assert route_by_intent(graph_state) == "plan_assess"

    assess_out = await node_plan_assess(ctx, graph_state)
    assert assess_out.get("assess_route") == "skip_generate"
    assert ctx.scratch.plan_result is not None
    assert len(ctx.scratch.plan_result.decision.steps) == 1
    assess_continuation.assert_awaited_once()


@pytest.mark.asyncio
async def test_continuation_simple_routes_to_assess_and_bootstraps() -> None:
    """Continuation+simple should use continuation-assess and may bootstrap a single step."""
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

    continuation = MagicMock()
    continuation.action = "bootstrap"
    continuation.reasoning = "Prior context already identifies one concrete next action."
    continuation.goal_progress = "medium"

    assess_continuation = AsyncMock(return_value=continuation)
    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.loop_planner.assess_continuation = assess_continuation
    strange_loop.plan_phase.generate_from_assessment = AsyncMock(
        side_effect=AssertionError("bootstrap path should not call plan_generate")
    )
    strange_loop.plan_phase.generate_lightweight = AsyncMock(
        side_effect=AssertionError("bootstrap path should not call lightweight generate")
    )
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
        "intake_label": IntakeLabel.SIMPLE,
    }
    assert route_by_intent(graph_state) == "plan_assess"

    assess_out = await node_plan_assess(ctx, graph_state)
    assert assess_out.get("assess_route") == "skip_generate"
    assert ctx.scratch.plan_result is not None
    assert len(ctx.scratch.plan_result.decision.steps) == 1
    assess_continuation.assert_awaited_once()
