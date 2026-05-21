"""Executor integration tests for parallel-branch predecessor ledger replay (RFC-214)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage


def _astream_messages(mock_agent: MagicMock) -> list:
    call_args = mock_agent.astream.call_args
    assert call_args is not None
    payload = call_args.args[0]
    assert isinstance(payload, dict)
    return payload["messages"]


@pytest.mark.asyncio
async def test_parallel_branch_prepends_predecessor_ledger_before_envelope() -> None:
    """Branched LangGraph thread receives transitive predecessor execute pairs then envelope."""
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step_a = StepAction(id="A", description="first", expected_output="o1")
    step_b = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step_b],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(
            content="ledger-human-A",
            phase="execute_step",
            step_id="A",
            thread_id="logical-t",
        ),
        LoopAIMessage(
            content="ledger-ai-A",
            phase="execute_step",
            step_id="A",
            thread_id="logical-t",
        ),
    ]
    state = LoopState(
        goal="Branch goal text",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        stream_thread_id="logical-t__pB",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 3
    assert messages[0].content == "ledger-human-A"
    assert messages[1].content == "ledger-ai-A"
    assert messages[0] is not ledger[0]
    assert messages[1] is not ledger[1]
    assert isinstance(messages[2], LoopHumanMessage)
    assert messages[2].phase == "execute_step"
    assert "<CURRENT_GOAL>" not in str(messages[2].content)
    assert "second" in str(messages[2].content)

    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__pB"


@pytest.mark.asyncio
async def test_parallel_branch_no_predecessors_when_step_has_no_dependencies() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step = StepAction(id="solo", description="alone", expected_output="o")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="hA", phase="execute_step", step_id="A"),
        LoopAIMessage(content="aA", phase="execute_step", step_id="A"),
    ]
    state = LoopState(
        goal="g",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step,
        "logical-t",
        stream_thread_id="logical-t__psolo",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 1
    assert isinstance(messages[0], LoopHumanMessage)
    assert "alone" in str(messages[0].content)


@pytest.mark.asyncio
async def test_same_thread_id_skips_predecessor_injection_even_with_loop_state() -> None:
    """Sequential / single-thread execute path must not replay ledger into graph input."""
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step_b = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_b],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="hA", phase="execute_step", step_id="A"),
        LoopAIMessage(content="aA", phase="execute_step", step_id="A"),
    ]
    state = LoopState(
        goal="g",
        thread_id="same",
        current_decision=decision,
        loop_messages=ledger,
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step_b,
        "same",
        stream_thread_id="same",
        loop_state=state,
    )

    assert len(_astream_messages(mock_agent)) == 1


@pytest.mark.asyncio
async def test_parallel_branch_without_loop_state_skips_predecessor_injection() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step_b = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        stream_thread_id="logical-t__pB",
        loop_state=None,
    )

    assert len(_astream_messages(mock_agent)) == 1


@pytest.mark.asyncio
async def test_parallel_branch_respects_plan_ledger_max_messages_cap() -> None:
    """Reuse plan_prompt_ledger.plan_ledger_max_messages as predecessor slice cap."""
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    cfg = MagicMock()
    cfg.agent_loop.plan_prompt_ledger.plan_ledger_max_messages = 3

    step_b = StepAction(
        id="B",
        description="consume",
        expected_output="o",
        dependencies=["A"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_b],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger: list = []
    for i in range(5):
        ledger.append(
            LoopHumanMessage(content=f"h{i}", phase="execute_step", step_id="A"),
        )
        ledger.append(LoopAIMessage(content=f"a{i}", phase="execute_step", step_id="A"))
    state = LoopState(
        goal="g",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
    )
    executor = Executor(mock_agent, config=cfg)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        stream_thread_id="logical-t__pB",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 4
    assert [m.content for m in messages[:3]] == ["h0", "a0", "h1"]
    assert isinstance(messages[3], LoopHumanMessage)


@pytest.mark.asyncio
async def test_parallel_branch_human_envelope_uses_logical_thread_id() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step = StepAction(id="X", description="d", expected_output="o")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="logical-t", current_decision=decision, loop_messages=[])
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step,
        "logical-t",
        stream_thread_id="logical-t__pX",
        loop_state=state,
    )

    env = _astream_messages(mock_agent)[0]
    assert getattr(env, "thread_id", None) == "logical-t"


@pytest.mark.asyncio
async def test_parallel_branch_without_current_decision_skips_predecessor_injection() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step_b = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    state = LoopState(
        goal="g",
        thread_id="logical-t",
        current_decision=None,
        loop_messages=[
            LoopHumanMessage(content="hA", phase="execute_step", step_id="A"),
            LoopAIMessage(content="aA", phase="execute_step", step_id="A"),
        ],
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        stream_thread_id="logical-t__pB",
        loop_state=state,
    )

    assert len(_astream_messages(mock_agent)) == 1


@pytest.mark.asyncio
async def test_parallel_branch_logs_when_predecessors_injected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=iter([]))

    step_b = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_b],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="hA", phase="execute_step", step_id="A"),
        LoopAIMessage(content="aA", phase="execute_step", step_id="A"),
    ]
    state = LoopState(
        goal="g",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
    )
    executor = Executor(mock_agent)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        stream_thread_id="logical-t__pB",
        loop_state=state,
    )

    assert "[BranchPred]" in caplog.text
    assert "injected" in caplog.text and "predecessor" in caplog.text
