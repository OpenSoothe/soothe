"""Ledger updates from ``goal_completion`` node (RFC-214)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage
from soothe.foundation.sloop.engine.synthesis import SynthesisGenerator
from soothe.foundation.sloop.orchestrator.nodes.goal_completion import node_goal_completion
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.schemas import LoopState, PlanResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.context.planning import StepPlanManagerAdapter
from soothe.foundation.context.planning.models import CompletionStrategy


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _ctx(
    *,
    loop_state: LoopState,
    plan_manager: StepPlanManagerAdapter,
    strange_loop: Mock,
    state_manager: Mock,
    plan_result: PlanResult,
    ce: ContextEngine,
    goal: GoalNode,
) -> LoopRuntimeContext:
    scratch = LoopPhaseScratch(plan_result=plan_result, iteration_perf_start=None)
    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=state_manager,
        anchor_manager=Mock(),
        goal_context_manager=Mock(),
        plan_manager=plan_manager,
        checkpoint=Mock(),
        goal_record=Mock(goal_id="g1"),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=scratch,
        ce=ce,
        ce_goal_id=goal.id,
    )


@pytest.mark.asyncio
async def test_synthesize_appends_goal_completion_ledger_pair() -> None:
    ce = _make_ce()
    loop_state = LoopState(goal="do thing", thread_id="thr-1")
    goal = GoalNode(description="do thing")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=True)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SYNTHESIZE)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    async def fake_gen(self, goal, state):  # noqa: ARG002
        yield ((), "messages", (AIMessage(content="final synth body"), {}))

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    with patch.object(SynthesisGenerator, "generate_synthesis", fake_gen):
        await node_goal_completion(ctx, {})

    completed_payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert completed_payload is not None
    assert completed_payload.get("skip_goal_completion_wire_duplicate") is True

    lm = loop_state.loop_messages
    assert len(lm) == 2
    assert isinstance(lm[0], LoopHumanMessage)
    assert lm[0].phase == "goal_completion"
    assert isinstance(lm[1], LoopAIMessage)
    assert lm[1].phase == "goal_completion"
    assert lm[1].content == "final synth body"
    assert lm[1].iteration == 0


@pytest.mark.asyncio
async def test_goal_completion_logs_planning_dag_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the unified DAG has nodes, goal completion logs it (not user output)."""
    from soothe.foundation.sloop.state.schemas import AgentDecision, StepAction, StepResult

    caplog.set_level(logging.INFO)
    ce = _make_ce()
    loop_state = LoopState(goal="goal txt", thread_id="thr-dag")
    goal = GoalNode(description="goal txt")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="ABC-01", description="One thing", dependencies=None)],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="done",
        goal_progress="complete",
        require_goal_completion=True,
        decision=decision,
    )
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.ingest_plan(plan_result, "ABC", 1)
    pm.record_step_outcomes(
        [
            StepResult(
                step_id="ABC-01",
                success=True,
                outcome={},
                error=None,
                duration_ms=1,
                thread_id="thr-dag",
            )
        ]
    )
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SYNTHESIZE)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    async def fake_gen(self, goal, state):  # noqa: ARG002
        yield ((), "messages", (AIMessage(content="synth only"), {}))

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    with patch.object(SynthesisGenerator, "generate_synthesis", fake_gen):
        await node_goal_completion(ctx, {})

    assert "Planning DAG at goal end" in caplog.text
    assert "ABC-01" in caplog.text
    lm = loop_state.loop_messages
    assert len(lm) == 2
    assert lm[1].content == "synth only"


@pytest.mark.asyncio
async def test_goal_completion_dag_reflects_finalized_goal_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The completion DAG log should reflect post-finalize CE goal status."""
    caplog.set_level(logging.INFO)
    ce = _make_ce()
    loop_state = LoopState(goal="count all file types", thread_id="thr-status")
    goal = GoalNode(description="count all file types", status="active")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=True)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SYNTHESIZE)
    status_when_reported: dict[str, str | None] = {"value": None}

    def fake_report() -> str:
        status_when_reported["value"] = ce.get_goal_sync(goal.id).status
        return "Mock DAG report"

    pm.format_completion_dag_report = Mock(side_effect=fake_report)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    async def fake_gen(self, goal, state):  # noqa: ARG002
        yield ((), "messages", (AIMessage(content="done"), {}))

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    with patch.object(SynthesisGenerator, "generate_synthesis", fake_gen):
        await node_goal_completion(ctx, {})

    assert "Planning DAG at goal end" in caplog.text
    assert "Mock DAG report" in caplog.text
    assert status_when_reported["value"] == "completed"


@pytest.mark.asyncio
async def test_ledger_direct_does_not_duplicate_completion_in_ledger() -> None:
    ce = _make_ce()
    loop_state = LoopState(goal="g", thread_id="thr-1")
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    ce.ledger.record_message(
        LoopHumanMessage(
            content="Execute: x",
            thread_id="thr-1",
            iteration=0,
            phase="execute_step",
        ),
        phase="execute_step",
    )
    ce.ledger.record_message(
        LoopAIMessage(
            content="already the answer",
            thread_id="thr-1",
            iteration=0,
            phase="execute_step",
        ),
        phase="execute_step",
    )
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    await node_goal_completion(ctx, {})

    completed_payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert completed_payload is not None
    assert completed_payload.get("skip_goal_completion_wire_duplicate") is False

    lm = loop_state.loop_messages
    assert len(lm) == 2
    assert lm[1].content == "already the answer"


@pytest.mark.asyncio
async def test_summary_completion_sets_skip_replay_false() -> None:
    ce = _make_ce()
    loop_state = LoopState(goal="g", thread_id="thr-1")
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SUMMARY)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    with patch(
        "soothe.foundation.sloop.orchestrator.nodes.goal_completion.generate_user_fallback_summary",
        return_value="fallback summary body",
    ):
        await node_goal_completion(ctx, {})

    completed_payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert completed_payload is not None
    assert completed_payload.get("skip_goal_completion_wire_duplicate") is False


@pytest.mark.asyncio
async def test_ledger_direct_filters_out_planning_messages_for_final_output() -> None:
    ce = _make_ce()
    loop_state = LoopState(goal="g", thread_id="thr-1")
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    ce.ledger.record_message(
        LoopHumanMessage(
            content="Execute: x",
            thread_id="thr-1",
            iteration=0,
            phase="execute_step",
        ),
        phase="execute_step",
    )
    ce.ledger.record_message(
        LoopAIMessage(
            content="execute answer",
            thread_id="thr-1",
            iteration=0,
            phase="execute_step",
        ),
        phase="execute_step",
    )
    ce.ledger.record_message(
        LoopHumanMessage(
            content="Assess if done",
            thread_id="thr-1",
            iteration=0,
            phase="plan_assess",
        ),
        phase="plan_assess",
    )
    ce.ledger.record_message(
        LoopAIMessage(
            content="status=done",
            thread_id="thr-1",
            iteration=0,
            phase="plan_assess",
        ),
        phase="plan_assess",
    )
    ce.ledger.record_message(
        LoopHumanMessage(
            content="Generate final structure",
            thread_id="thr-1",
            iteration=0,
            phase="plan_generate",
        ),
        phase="plan_generate",
    )
    ce.ledger.record_message(
        LoopAIMessage(
            content="planner generated text",
            thread_id="thr-1",
            iteration=0,
            phase="plan_generate",
        ),
        phase="plan_generate",
    )
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    await node_goal_completion(ctx, {})

    completed_payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert completed_payload is not None
    assert completed_payload["result"].full_output == "execute answer"


@pytest.mark.asyncio
async def test_goal_completion_emits_finalize_phase_status() -> None:
    ce = _make_ce()
    loop_state = LoopState(goal="g", thread_id="thr-phase")
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.loop_planner._model = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    await node_goal_completion(ctx, {})

    phase_emits = [
        c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "plan_phase_status"
    ]
    assert phase_emits
    assert phase_emits[0]["label"] == "Finalizing goal"
