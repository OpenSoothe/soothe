"""Planner-emitted ``ask_user`` step routing through ``node_execute`` (IG-462)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.clarification import (
    ClarificationAnswer,
    answer_to_state,
    request_from_state,
)
from soothe.foundation.sloop.engine.executor import StepWaveStart
from soothe.foundation.sloop.orchestrator.nodes.execute_steps import (
    PLANNER_ASK_INTERRUPT_PREFIX,
    node_execute,
)
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.schemas import AgentDecision, StepAction, StepResult


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_loop_state() -> Any:
    loop_state = MagicMock()
    loop_state.dependency_completion_ids.return_value = set()
    loop_state.workspace = None
    loop_state.thread_id = "thread-1"
    loop_state.working_memory = None
    loop_state.add_step_result = MagicMock()
    loop_state.step_results = []
    loop_state.iteration = 0
    loop_state.goal = "test goal"
    loop_state.loop_messages = []
    return loop_state


def _make_ctx(
    decision: AgentDecision,
    emit_sink: list[tuple[str, Any]],
    *,
    clarification_policy: Any = None,
    loop_state: Any | None = None,
    ce: ContextEngine | None = None,
    goal: GoalNode | None = None,
) -> LoopRuntimeContext:
    async def emit(event_type: str, event_data: Any) -> None:
        emit_sink.append((event_type, event_data))

    state = loop_state if loop_state is not None else _make_loop_state()

    scratch = MagicMock()
    scratch.decision = decision
    scratch.plan_result = MagicMock()

    strange_loop = MagicMock()
    strange_loop.config.agent.loop.concurrency.max_parallel_steps = 4
    strange_loop.core_agent.graph.checkpointer = None

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-1"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=emit,
        scratch=scratch,
        clarification_policy=clarification_policy,
        ce=ce,
        ce_goal_id=goal.id if goal else None,
    )


@pytest.mark.asyncio
async def test_branch2_short_circuits_when_planner_emits_ask_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a ready step has ``kind="ask_user"``, node_execute must NOT invoke the
    Executor — it must return ``pending_clarification`` keyed by the sentinel
    interrupt id so the graph routes to ``await_clarification``."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="ASK-01",
                description="ask about format",
                kind="ask_user",
                questions=["Which output format?"],
            ),
        ],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    ce = _make_ce()
    goal = GoalNode(description="test goal")
    ce._dag.add_goal(goal)
    ctx = _make_ctx(decision, emitted, clarification_policy=object(), ce=ce, goal=goal)

    executor_called = MagicMock()

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", executor_called)

    result = await node_execute(ctx, {})

    executor_called.assert_not_called()
    assert "pending_clarification" in result
    assert result["last_clarification_origin"] == "execute"
    assert result["pending_clarification_answer"] is None

    pending = request_from_state(result["pending_clarification"])
    assert pending.questions == ("Which output format?",)
    assert pending.origin_node == "execute"
    assert pending.origin_interrupt_id == f"{PLANNER_ASK_INTERRUPT_PREFIX}ASK-01"

    started = [e for e in emitted if e[0] == "step_started"]
    assert [s[1]["step_id"] for s in started] == ["ASK-01"]


@pytest.mark.asyncio
async def test_branch2_noop_when_no_clarification_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a clarification policy, an ask_user step falls through to the
    legacy executor path (it will be treated as a normal step / no-op)."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="ASK-01",
                description="ask",
                kind="ask_user",
                questions=["Which?"],
            )
        ],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    ctx = _make_ctx(decision, emitted, clarification_policy=None)

    async def _empty_stream(*_a: Any, **_k: Any):
        if False:
            yield None

    mock_executor = MagicMock()
    mock_executor.execute = _empty_stream

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", MagicMock(return_value=mock_executor))

    result = await node_execute(ctx, {})

    assert "pending_clarification" not in result


@pytest.mark.asyncio
async def test_branch1_synthesizes_step_result_from_planner_ask_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On re-entry with a planner-ask answer, node_execute records a successful
    StepResult for the matching step id, clears pending_clarification_answer,
    and DOES NOT pass a resume payload to the executor."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="ASK-01",
                description="ask about format",
                kind="ask_user",
                questions=["Which output format?"],
            )
        ],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    loop_state = _make_loop_state()
    # Simulate that the answered step id is already considered complete by
    # state when get_ready_steps runs (which it would be after add_step_result).
    ce = _make_ce()
    goal = GoalNode(description="test goal")
    ce._dag.add_goal(goal)
    ctx = _make_ctx(
        decision, emitted, clarification_policy=object(), loop_state=loop_state, ce=ce, goal=goal
    )

    pending_clar = {
        "questions": ["Which output format?"],
        "origin_node": "execute",
        "origin_interrupt_id": f"{PLANNER_ASK_INTERRUPT_PREFIX}ASK-01",
        "loop_state": {
            "goal_id": "",
            "goal_description": "",
            "user_request": "",
            "iteration": 0,
            "intent_classification": None,
            "plan_summary": None,
            "recent_step_outputs": [],
            "workspace_summary": None,
            "active_skills": [],
            "active_mcp_servers": [],
        },
    }
    answer = ClarificationAnswer(answers=("json",), source="veritas", confidence=0.9)
    pending_ans = answer_to_state(answer)

    async def _empty_stream(*_a: Any, **_k: Any):
        # After the synthesized StepResult is recorded, the answered step id is
        # in dependency_completion_ids so the executor finds nothing to run.
        if False:
            yield None

    captured_executor_kwargs: dict[str, Any] = {}
    executor_called = False

    def _factory(*args: Any, **kwargs: Any) -> Any:
        nonlocal executor_called
        executor_called = True
        captured_executor_kwargs.update(kwargs)
        mock_ex = MagicMock()
        mock_ex.execute = _empty_stream
        return mock_ex

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", _factory)

    result = await node_execute(
        ctx,
        {
            "pending_clarification": pending_clar,
            "pending_clarification_answer": pending_ans,
        },
    )

    # The synthesized StepResult was applied to loop state.
    assert loop_state.add_step_result.call_count == 1
    applied = loop_state.add_step_result.call_args.args[0]
    assert isinstance(applied, StepResult)
    assert applied.step_id == "ASK-01"
    assert applied.success is True
    assert applied.outcome["kind"] == "ask_user"
    assert applied.outcome["answers"] == ["json"]
    assert applied.outcome["source"] == "veritas"
    # The Q&A is also captured on the outcome so plan-assess/plan-generate can
    # reference what was asked.
    assert applied.outcome["questions"] == ["Which output format?"]
    assert applied.outcome["confidence"] == pytest.approx(0.9)

    # The Q&A pair was appended to CE ledger so the next plan iteration
    # sees the resolved clarification (otherwise the planner re-asks).
    msgs = ce.ledger.get_messages()
    assert len(msgs) == 2
    human_msg, ai_msg = msgs
    assert human_msg.type == "human"
    assert "Which output format?" in human_msg.content
    assert ai_msg.type == "ai"
    assert "json" in ai_msg.content
    assert "veritas" in ai_msg.content

    # step_completed event mirrors the synthesized result and carries the
    # ``clarification`` payload for TUIs to render the Q&A on the step card.
    completed = [e for e in emitted if e[0] == "step_completed"]
    assert len(completed) == 1
    assert completed[0][1]["step_id"] == "ASK-01"
    assert completed[0][1]["success"] is True
    clarification = completed[0][1].get("clarification")
    assert clarification is not None
    assert clarification["questions"] == ["Which output format?"]
    assert clarification["answers"] == ["json"]
    assert clarification["source"] == "veritas"
    assert clarification["confidence"] == pytest.approx(0.9)

    # Executor was invoked with resume_answer_payload=None (no fake interrupt key).
    assert captured_executor_kwargs.get("clarification_resume_answer_payload") is None
    assert executor_called is True

    # Must not re-route to await_clarification for the step we just answered.
    assert not result.get("pending_clarification")

    # Answer state is cleared so the next iteration doesn't re-consume it.
    assert result["pending_clarification_answer"] is None


@pytest.mark.asyncio
async def test_branch1_ce_bound_does_not_re_emit_planner_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CE-bound loop state must persist the synth result before Branch 2 runs."""
    from soothe.foundation.context.models import StepNode
    from soothe.foundation.sloop.state.schemas import LoopState

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="ASK-01",
                description="Ask which aspect to prioritize",
                kind="ask_user",
                questions=["Which output format?"],
            ),
        ],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    ce = _make_ce()
    goal = GoalNode(description="test goal")
    ce._dag.add_goal(goal)
    await ce.add_steps(
        goal.id,
        [StepNode(id="ASK-01", description="Ask which aspect to prioritize")],
    )

    loop_state = LoopState(
        goal="test goal",
        thread_id="thread-1",
        workspace=None,
        iteration=0,
        max_iterations=10,
    )
    loop_state.bind_ce(ce, goal.id)
    loop_state.current_decision = decision

    plan_manager = MagicMock()
    ctx = _make_ctx(
        decision,
        emitted,
        clarification_policy=object(),
        loop_state=loop_state,
        ce=ce,
        goal=goal,
    )
    ctx.plan_manager = plan_manager

    executor_called = False

    async def _empty_stream(*_a: Any, **_k: Any):
        nonlocal executor_called
        executor_called = True
        if False:
            yield None

    mock_executor = MagicMock()
    mock_executor.execute = _empty_stream

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", MagicMock(return_value=mock_executor))

    pending_clar = {
        "questions": ["Which output format?"],
        "origin_node": "execute",
        "origin_interrupt_id": f"{PLANNER_ASK_INTERRUPT_PREFIX}ASK-01",
        "loop_state": {
            "goal_id": "",
            "goal_description": "",
            "user_request": "",
            "iteration": 0,
            "intent_classification": None,
            "plan_summary": None,
            "recent_step_outputs": [],
            "workspace_summary": None,
            "active_skills": [],
            "active_mcp_servers": [],
        },
    }
    answer = ClarificationAnswer(answers=("json",), source="veritas", confidence=0.9)

    result = await node_execute(
        ctx,
        {
            "pending_clarification": pending_clar,
            "pending_clarification_answer": answer_to_state(answer),
        },
    )

    assert not result.get("pending_clarification")
    assert result["pending_clarification_answer"] is None
    assert executor_called is True
    plan_manager.record_step_outcomes.assert_called_once()
    assert "ASK-01" in loop_state.dependency_completion_ids()


@pytest.mark.asyncio
async def test_branch2_picks_first_ask_user_in_mixed_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a wave has multiple ready steps and one of them is ask_user, the
    short-circuit fires first; non-ask steps run on the resumed wave."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="ACT-01", description="explore"),
            StepAction(
                id="ASK-02",
                description="ask",
                kind="ask_user",
                questions=["Which?"],
            ),
        ],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    ce = _make_ce()
    goal = GoalNode(description="test goal")
    ce._dag.add_goal(goal)
    ctx = _make_ctx(decision, emitted, clarification_policy=object(), ce=ce, goal=goal)

    executor_called = MagicMock()

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", executor_called)

    result = await node_execute(ctx, {})

    executor_called.assert_not_called()
    pending = request_from_state(result["pending_clarification"])
    assert pending.origin_interrupt_id == f"{PLANNER_ASK_INTERRUPT_PREFIX}ASK-02"


@pytest.mark.asyncio
async def test_real_coreagent_resume_payload_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regular CoreAgent ask_user interrupt (no ``planner-ask:`` prefix)
    should still build ``resume_answer_payload`` for the executor."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="ACT-01", description="do thing")],
        execution_mode="parallel",
    )
    emitted: list[tuple[str, Any]] = []
    ctx = _make_ctx(decision, emitted, clarification_policy=None)

    pending_clar = {
        "questions": ["Real ask?"],
        "origin_node": "execute",
        "origin_interrupt_id": "real-interrupt-xyz",
        "loop_state": {
            "goal_id": "",
            "goal_description": "",
            "user_request": "",
            "iteration": 0,
            "intent_classification": None,
            "plan_summary": None,
            "recent_step_outputs": [],
            "workspace_summary": None,
            "active_skills": [],
            "active_mcp_servers": [],
        },
    }
    answer = ClarificationAnswer(answers=("ok",), source="human", confidence=1.0)
    pending_ans = answer_to_state(answer)

    async def _yield_wave(*_a: Any, **_k: Any):
        yield StepWaveStart(steps=(StepAction(id="ACT-01", description="do thing"),))
        yield StepResult(
            step_id="ACT-01",
            success=True,
            duration_ms=1,
            thread_id="thread-1",
            tool_call_count=0,
        )

    captured: dict[str, Any] = {}

    def _factory(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        mock_ex = MagicMock()
        mock_ex.execute = _yield_wave
        return mock_ex

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    monkeypatch.setattr(mod, "Executor", _factory)

    await node_execute(
        ctx,
        {
            "pending_clarification": pending_clar,
            "pending_clarification_answer": pending_ans,
        },
    )

    # Real CoreAgent interrupt id → resume_answer_payload keyed by that id.
    payload = captured.get("clarification_resume_answer_payload")
    assert payload == {"real-interrupt-xyz": {"answers": ["ok"]}}


@pytest.mark.asyncio
async def test_synth_path_persists_qa_pair_to_goal_record() -> None:
    """When the resume path synthesizes a step result without a scratch decision,
    the appended Q&A pair must be mirrored onto ``goal_record.loop_messages`` and
    the checkpoint persisted. Without this, the next clarification round trip
    reloads ``goal_record`` with a stale ledger and plan-assess / plan-generate
    re-ask the same question."""
    from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

    emitted: list[tuple[str, Any]] = []

    # Real LoopState so loop_messages is a list we can mutate and read back.
    from soothe.foundation.sloop.state.schemas import LoopState

    ce = _make_ce()
    loop_state = LoopState(
        goal="count file types per package",
        thread_id="thread-1",
        workspace=None,
        iteration=2,
        max_iterations=10,
    )
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    # Simulate prior plan-phase pairs already on the CE ledger that
    # never reached the goal record (synth path runs before record_iteration).
    ce.ledger.record_message(
        LoopHumanMessage(content="prior assess", thread_id="thread-1", iteration=1),
        phase="plan_assess",
    )
    ce.ledger.record_message(
        LoopAIMessage(content="prior assess A", thread_id="thread-1", iteration=1),
        phase="plan_assess",
    )

    goal_record = MagicMock()

    # state_manager.save is awaited; capture the checkpoint argument.
    save_calls: list[Any] = []

    class _StateManager:
        loop_id = "loop-1"

        async def save(self, ckpt: Any) -> None:
            save_calls.append(ckpt)

    async def emit(event_type: str, event_data: Any) -> None:
        emitted.append((event_type, event_data))

    # Synth path is hit when scratch.decision/plan_result are None.
    scratch = MagicMock()
    scratch.decision = None
    scratch.plan_result = None

    strange_loop = MagicMock()
    strange_loop.config.agent.loop.concurrency.max_parallel_steps = 4
    strange_loop.core_agent.graph.checkpointer = None

    checkpoint_obj = MagicMock()

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=_StateManager(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=checkpoint_obj,
        goal_record=goal_record,
        continue_loop_mode=False,
        recovery_valid_resume=True,
        loop_state=loop_state,
        emit=emit,
        scratch=scratch,
        clarification_policy=None,
        ce=ce,
        ce_goal_id=goal.id,
    )

    pending_clar = {
        "questions": ["Which package next?"],
        "origin_node": "execute",
        "origin_interrupt_id": f"{PLANNER_ASK_INTERRUPT_PREFIX}ASK-03",
        "loop_state": {
            "goal_id": "",
            "goal_description": "",
            "user_request": "",
            "iteration": 0,
            "intent_classification": None,
            "plan_summary": None,
            "recent_step_outputs": [],
            "workspace_summary": None,
            "active_skills": [],
            "active_mcp_servers": [],
        },
    }
    answer = ClarificationAnswer(answers=("soothe-daemon",), source="human")
    pending_ans = answer_to_state(answer)

    result = await node_execute(
        ctx,
        {
            "pending_clarification": pending_clar,
            "pending_clarification_answer": pending_ans,
        },
    )

    # Synth path was taken.
    assert result.get("resume_synth") is True
    # State got the new Q&A pair appended (2 prior + 2 new = 4).
    msgs = ce.ledger.get_messages()
    assert len(msgs) == 4
    new_human, new_ai = msgs[-2:]
    assert "Which package next?" in new_human.content
    assert "soothe-daemon" in new_ai.content

    # RFC-626: iteration lives on LoopState / execution_checkpoint, not goal index.
    assert loop_state.iteration == 3  # 2 → +1 in synth path

    # Checkpoint was persisted exactly once with our checkpoint object.
    assert save_calls == [checkpoint_obj]
