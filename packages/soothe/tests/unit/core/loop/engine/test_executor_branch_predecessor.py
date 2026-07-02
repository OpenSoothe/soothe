"""Executor integration tests for thread isolation and predecessor message injection (IG-477)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    """Empty async generator for mocking agent.execution_astream."""
    if False:  # pragma: no cover - never yields
        yield


def _make_mock_agent() -> MagicMock:
    """Create mock agent with async generator execution_astream."""
    mock_agent = MagicMock()
    # execution_astream is sync and returns an async iterator — not awaitable.
    mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
    mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
    mock_agent.aget_state = AsyncMock(return_value=MagicMock())
    return mock_agent


def _make_mock_checkpointer() -> MagicMock:
    """Create mock checkpointer (execute path no longer forks checkpoints)."""
    return MagicMock()


def _astream_messages(mock_agent: MagicMock) -> list:
    call_args = mock_agent.execution_astream.call_args
    assert call_args is not None
    payload = call_args.args[0]
    assert isinstance(payload, dict)
    return payload["messages"]


@pytest.mark.asyncio
async def test_multi_dep_step_uses_ledger_projection() -> None:
    """Multi-dependency steps ground predecessors via ledger projection, not envelope injection."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step_a = StepAction(id="A", description="first", expected_output="o1")
    step_b = StepAction(id="B", description="second", expected_output="o2")
    step_c = StepAction(
        id="C",
        description="third",
        expected_output="o3",
        dependencies=["A", "B"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step_b, step_c],
        execution_mode="dependency",
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
        LoopHumanMessage(
            content="ledger-human-B",
            phase="execute_step",
            step_id="B",
            thread_id="logical-t",
        ),
        LoopAIMessage(
            content="ledger-ai-B",
            phase="execute_step",
            step_id="B",
            thread_id="logical-t",
        ),
    ]
    state = LoopState(
        goal="Test goal",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
        step_thread_ids={"A": "logical-t__step_A", "B": "logical-t__step_B"},
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_c,
        "logical-t",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 5
    envelope = str(messages[-1].content)
    assert "PRIOR STEPS:" in envelope
    assert "PRIOR STEP EVIDENCE" not in envelope
    assert "(completed)" in envelope
    assert "first" in envelope or "second" in envelope
    assert "ledger-ai-A" in str(messages[1].content)
    assert "ledger-ai-B" in str(messages[3].content)
    assert "ledger-human-A" in str(messages[0].content)
    assert "third" in envelope

    cfg = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_C"


@pytest.mark.asyncio
async def test_singleton_dependent_step_uses_fresh_thread_and_ledger_projection() -> None:
    """Dependent steps use a fresh thread; predecessor context is projected from the ledger."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

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
        execution_mode="dependency",
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
            content="ledger-ai-A with failure details",
            phase="execute_step",
            step_id="A",
            thread_id="logical-t",
        ),
    ]
    state = LoopState(
        goal="Test goal",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
        step_thread_ids={"A": "logical-t__step_A"},
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        loop_state=state,
    )

    cfg = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_B"
    assert state.step_thread_ids.get("B") == "logical-t__step_B"

    messages = _astream_messages(mock_agent)
    assert len(messages) == 3
    envelope = str(messages[-1].content)
    assert "PRIOR STEPS:" in envelope
    assert "PRIOR STEP EVIDENCE" not in envelope
    assert "(completed)" in envelope
    assert "ledger-ai-A with failure details" in str(messages[1].content)
    assert "do not repeat completed discovery steps" in envelope
    assert "ledger-human-A" in str(messages[0].content)


@pytest.mark.asyncio
async def test_no_dep_step_forks_from_main_thread() -> None:
    """Steps with no dependencies fork from main thread."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step = StepAction(id="solo", description="alone", expected_output="o")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(
        goal="g",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=[],
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step,
        "logical-t",
        loop_state=state,
    )

    cfg = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_solo"
    assert state.step_thread_ids.get("solo") == "logical-t__step_solo"


@pytest.mark.asyncio
async def test_step_without_loop_state_uses_main_thread() -> None:
    """Without loop_state, step uses main thread (no fork)."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step = StepAction(
        id="B",
        description="second",
        expected_output="o2",
        dependencies=["A"],
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step,
        "logical-t",
        loop_state=None,
    )

    cfg = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t"


@pytest.mark.asyncio
async def test_multi_dep_replays_predecessor_ledger_rows() -> None:
    """Dependent steps prepend transitive-predecessor execute ledger rows before the envelope."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step_c = StepAction(
        id="C",
        description="consume",
        expected_output="o",
        dependencies=["A", "B"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_c],
        execution_mode="dependency",
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
        step_thread_ids={"A": "logical-t__step_A", "B": "logical-t__step_B"},
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_c,
        "logical-t",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 11
    assert str(messages[-1].content).startswith("EXECUTION TASK:")
    assert "PRIOR STEP EVIDENCE" not in str(messages[-1].content)


@pytest.mark.asyncio
async def test_execute_envelope_uses_logical_thread_id() -> None:
    """Human envelope message uses logical thread_id regardless of fork."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step = StepAction(id="X", description="d", expected_output="o")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="logical-t", current_decision=decision, loop_messages=[])
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step,
        "logical-t",
        loop_state=state,
    )

    env = _astream_messages(mock_agent)[0]
    assert getattr(env, "thread_id", None) == "logical-t"


@pytest.mark.asyncio
async def test_step_without_current_decision_uses_main_thread() -> None:
    """Without current_decision in loop_state, step uses main thread."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

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
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        loop_state=state,
    )

    cfg = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t"


@pytest.mark.asyncio
async def test_multi_dep_projects_predecessor_ledger_without_threadfork_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dependent steps project predecessor ledger rows without checkpoint fork logging."""
    caplog.set_level(logging.INFO)

    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step_c = StepAction(
        id="C",
        description="third",
        expected_output="o3",
        dependencies=["A", "B"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_c],
        execution_mode="dependency",
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
        step_thread_ids={"A": "logical-t__step_A", "B": "logical-t__step_B"},
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_c,
        "logical-t",
        loop_state=state,
    )

    assert "[ThreadFork]" not in caplog.text
    messages = _astream_messages(mock_agent)
    assert len(messages) == 3
    assert "aA" in str(messages[1].content)


@pytest.mark.asyncio
async def test_hydrate_dependent_steps_sets_full_description_from_evidence() -> None:
    """P2: vague dependent briefs are expanded before the execute wave runs."""
    step_a = StepAction(id="01", description="Run verification")
    step_b = StepAction(
        id="02",
        description="Fix identified test or lint failures",
        dependencies=["01"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step_b],
        execution_mode="dependency",
        reasoning="r",
    )
    state = LoopState(
        goal="fix repo",
        thread_id="t1",
        current_decision=decision,
        loop_messages=[
            LoopAIMessage(
                content="verify_finally — pre-commit checks\n✗ F821 undefined name `Any`",
                phase="execute_step",
                step_id="01",
                thread_id="t1",
            ),
        ],
    )
    executor = Executor(_make_mock_agent())

    await executor._hydrate_dependent_steps_before_wave([step_b], state, decision)

    assert step_b.full_description
    assert "F821" in step_b.full_description
    assert "Do NOT repeat discovery" in step_b.full_description


@pytest.mark.asyncio
async def test_hydrate_dependent_steps_skipped_when_disabled() -> None:
    cfg = MagicMock()
    cfg.agent.loop.step_brief_hydration_enabled = False
    step = StepAction(
        id="02",
        description="Fix identified failures",
        dependencies=["01"],
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step, StepAction(id="01", description="verify")],
        execution_mode="dependency",
        reasoning="r",
    )
    state = LoopState(
        goal="fix repo",
        thread_id="t1",
        current_decision=decision,
        loop_messages=[
            LoopAIMessage(
                content="lint error in foo.py",
                phase="execute_step",
                step_id="01",
                thread_id="t1",
            ),
        ],
    )
    executor = Executor(_make_mock_agent(), config=cfg)

    await executor._hydrate_dependent_steps_before_wave([step], state, decision)

    assert step.full_description is None


@pytest.mark.asyncio
async def test_continue_loop_bootstrap_projects_goal_completion_ledger() -> None:
    """Loop continuation bootstrap projects prior goal completion via Slice A ledger."""
    mock_agent = _make_mock_agent()
    step = StepAction(id="bootstrap", description="Continue prior work")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    completion_body = (
        "## Recommendations\nImplement envelope-only continuation grounding for the next goal."
    )
    ledger = [
        LoopHumanMessage(
            content="ledger-human-prior",
            phase="execute_step",
            step_id="MUY-01",
            thread_id="logical-t",
        ),
        LoopAIMessage(
            content="ledger-ai-prior git diff output",
            phase="execute_step",
            step_id="MUY-01",
            thread_id="logical-t",
        ),
        LoopAIMessage(
            content=completion_body,
            phase="goal_completion",
            thread_id="logical-t",
        ),
    ]
    state = LoopState(
        goal="continue",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
        iteration=0,
    )

    await Executor._execute_step_collecting_events(
        Executor(mock_agent),
        step,
        "logical-t",
        loop_state=state,
        continue_loop_mode=True,
    )

    messages = _astream_messages(mock_agent)
    assert len(messages) == 2
    envelope = str(getattr(messages[-1], "content", ""))
    assert "PRIOR GOAL COMPLETION:\n" not in envelope
    assert completion_body in str(getattr(messages[0], "content", ""))
    assert "ledger-human-prior" not in envelope
    assert "ledger-ai-prior git diff output" not in envelope
