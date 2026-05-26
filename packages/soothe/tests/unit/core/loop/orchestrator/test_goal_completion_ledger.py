"""Ledger updates from ``goal_completion`` node (RFC-214)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage

from soothe.core.loop.engine.synthesis import SynthesisGenerator
from soothe.core.loop.orchestrator.nodes.goal_completion import node_goal_completion
from soothe.core.loop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.core.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.core.loop.planning.manager import CompletionStrategy, PlanManager
from soothe.core.loop.state.schemas import LoopState, PlanResult
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage


def _ctx(
    *,
    loop_state: LoopState,
    plan_manager: PlanManager,
    agent_loop: Mock,
    state_manager: Mock,
    plan_result: PlanResult,
) -> LoopRuntimeContext:
    scratch = LoopPhaseScratch(plan_result=plan_result, iteration_perf_start=None)
    return LoopRuntimeContext(
        agent_loop=agent_loop,
        state_manager=state_manager,
        anchor_manager=Mock(),
        goal_context_manager=Mock(),
        plan_manager=plan_manager,
        checkpoint=Mock(),
        goal_record=Mock(goal_id="g1"),
        continue_thread_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=scratch,
    )


@pytest.mark.asyncio
async def test_synthesize_appends_goal_completion_ledger_pair() -> None:
    loop_state = LoopState(goal="do thing", thread_id="thr-1", loop_messages=[])
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=True)
    pm = PlanManager(goal="do thing")
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SYNTHESIZE)

    agent_loop = Mock()
    agent_loop.loop_planner = Mock()
    agent_loop.loop_planner._model = Mock()
    agent_loop.core_agent = Mock()
    agent_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    async def fake_gen(self, goal, state):  # noqa: ARG002
        yield ((), "messages", (AIMessage(content="final synth body"), {}))

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        agent_loop=agent_loop,
        state_manager=sm,
        plan_result=plan_result,
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
    from soothe.core.loop.state.schemas import AgentDecision, StepAction, StepResult

    caplog.set_level(logging.INFO)
    loop_state = LoopState(goal="goal txt", thread_id="thr-dag", loop_messages=[])
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
    pm = PlanManager(goal="goal txt")
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

    agent_loop = Mock()
    agent_loop.loop_planner = Mock()
    agent_loop.loop_planner._model = Mock()
    agent_loop.core_agent = Mock()
    agent_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    async def fake_gen(self, goal, state):  # noqa: ARG002
        yield ((), "messages", (AIMessage(content="synth only"), {}))

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        agent_loop=agent_loop,
        state_manager=sm,
        plan_result=plan_result,
    )

    with patch.object(SynthesisGenerator, "generate_synthesis", fake_gen):
        await node_goal_completion(ctx, {})

    assert "Planning DAG at goal end" in caplog.text
    assert "ABC-01" in caplog.text
    lm = loop_state.loop_messages
    assert len(lm) == 2
    assert lm[1].content == "synth only"


@pytest.mark.asyncio
async def test_ledger_direct_does_not_duplicate_completion_in_ledger() -> None:
    loop_state = LoopState(goal="g", thread_id="thr-1", loop_messages=[])
    loop_state.loop_messages.extend(
        [
            LoopHumanMessage(
                content="Execute: x",
                thread_id="thr-1",
                iteration=0,
                phase="execute_step",
            ),
            LoopAIMessage(
                content="already the answer",
                thread_id="thr-1",
                iteration=0,
                phase="execute_step",
            ),
        ]
    )
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = PlanManager(goal="g")
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    agent_loop = Mock()
    agent_loop.loop_planner = Mock()
    agent_loop.loop_planner._model = Mock()
    agent_loop.core_agent = Mock()
    agent_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        agent_loop=agent_loop,
        state_manager=sm,
        plan_result=plan_result,
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
    loop_state = LoopState(goal="g", thread_id="thr-1", loop_messages=[])
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = PlanManager(goal="g")
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.SUMMARY)

    agent_loop = Mock()
    agent_loop.loop_planner = Mock()
    agent_loop.loop_planner._model = Mock()
    agent_loop.core_agent = Mock()
    agent_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        agent_loop=agent_loop,
        state_manager=sm,
        plan_result=plan_result,
    )

    with patch(
        "soothe.core.loop.orchestrator.nodes.goal_completion.generate_user_fallback_summary",
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
    loop_state = LoopState(goal="g", thread_id="thr-1", loop_messages=[])
    loop_state.loop_messages.extend(
        [
            LoopHumanMessage(
                content="Execute: x",
                thread_id="thr-1",
                iteration=0,
                phase="execute_step",
            ),
            LoopAIMessage(
                content="execute answer",
                thread_id="thr-1",
                iteration=0,
                phase="execute_step",
            ),
            LoopHumanMessage(
                content="Assess if done",
                thread_id="thr-1",
                iteration=0,
                phase="plan_assess",
            ),
            LoopAIMessage(
                content="status=done",
                thread_id="thr-1",
                iteration=0,
                phase="plan_assess",
            ),
            LoopHumanMessage(
                content="Generate final structure",
                thread_id="thr-1",
                iteration=0,
                phase="plan_generate",
            ),
            LoopAIMessage(
                content="planner generated text",
                thread_id="thr-1",
                iteration=0,
                phase="plan_generate",
            ),
        ]
    )
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = PlanManager(goal="g")
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    agent_loop = Mock()
    agent_loop.loop_planner = Mock()
    agent_loop.loop_planner._model = Mock()
    agent_loop.core_agent = Mock()
    agent_loop.config.agent.loop.final_response = "adaptive"

    sm = Mock()
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        agent_loop=agent_loop,
        state_manager=sm,
        plan_result=plan_result,
    )

    await node_goal_completion(ctx, {})

    completed_payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert completed_payload is not None
    assert completed_payload["result"].full_output == "execute answer"
