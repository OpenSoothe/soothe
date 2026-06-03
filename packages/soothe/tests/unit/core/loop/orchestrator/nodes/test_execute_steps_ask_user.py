"""Planner-emitted ``ask_user`` step routing through ``node_execute`` (IG-462)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.core.loop.clarification import (
    ClarificationAnswer,
    answer_to_state,
    request_from_state,
)
from soothe.core.loop.engine.executor import StepWaveStart
from soothe.core.loop.orchestrator.nodes.execute_steps import (
    PLANNER_ASK_INTERRUPT_PREFIX,
    node_execute,
)
from soothe.core.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.core.loop.state.schemas import AgentDecision, StepAction, StepResult


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
) -> LoopRuntimeContext:
    async def emit(event_type: str, event_data: Any) -> None:
        emit_sink.append((event_type, event_data))

    state = loop_state if loop_state is not None else _make_loop_state()

    scratch = MagicMock()
    scratch.decision = decision
    scratch.plan_result = MagicMock()

    agent_loop = MagicMock()
    agent_loop.config.agent.loop.limits.max_parallel_steps = 4
    agent_loop.core_agent.graph.checkpointer = None

    return LoopRuntimeContext(
        agent_loop=agent_loop,
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
    ctx = _make_ctx(decision, emitted, clarification_policy=object())

    executor_called = MagicMock()

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

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

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

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
    ctx = _make_ctx(decision, emitted, clarification_policy=object(), loop_state=loop_state)

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

    def _factory(*args: Any, **kwargs: Any) -> Any:
        captured_executor_kwargs.update(kwargs)
        mock_ex = MagicMock()
        mock_ex.execute = _empty_stream
        return mock_ex

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

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

    # The Q&A pair was appended to loop_messages so the next plan iteration
    # sees the resolved clarification (otherwise the planner re-asks).
    assert len(loop_state.loop_messages) == 2
    human_msg, ai_msg = loop_state.loop_messages
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

    # Answer state is cleared so the next iteration doesn't re-consume it.
    assert result["pending_clarification_answer"] is None


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
    ctx = _make_ctx(decision, emitted, clarification_policy=object())

    executor_called = MagicMock()

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

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

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

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
