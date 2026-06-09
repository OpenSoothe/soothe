"""Executor integration tests for thread fork predecessor handling (RFC-223)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.loop.engine.executor import Executor
from soothe.foundation.loop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    """Empty async generator for mocking agent.astream."""
    if False:  # pragma: no cover - never yields
        yield


def _make_mock_agent() -> MagicMock:
    """Create mock agent with async generator astream."""
    mock_agent = MagicMock()
    mock_agent.astream = AsyncMock(return_value=_empty_async_gen())
    return mock_agent


def _make_mock_checkpointer() -> MagicMock:
    """Create mock checkpointer with async copy_thread."""
    mock_checkpointer = MagicMock()
    mock_checkpointer.acopy_thread = AsyncMock()
    return mock_checkpointer


def _astream_messages(mock_agent: MagicMock) -> list:
    call_args = mock_agent.astream.call_args
    assert call_args is not None
    payload = call_args.args[0]
    assert isinstance(payload, dict)
    return payload["messages"]


@pytest.mark.asyncio
async def test_multi_dep_step_injects_transitive_predecessor_ledger() -> None:
    """Multi-dependency steps inject transitive predecessor ledger messages."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step_a = StepAction(id="A", description="first", expected_output="o1")
    step_b = StepAction(id="B", description="second", expected_output="o2")
    step_c = StepAction(
        id="C",
        description="third",
        expected_output="o3",
        dependencies=["A", "B"],  # Multi-dep triggers message injection
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

    # Multi-dep steps inject predecessor messages (transitive closure)
    messages = _astream_messages(mock_agent)
    # Should have predecessor messages + execute envelope
    assert len(messages) >= 1
    # Last message should be the execute envelope
    assert isinstance(messages[-1], LoopHumanMessage)
    assert messages[-1].phase == "execute_step"
    assert "third" in str(messages[-1].content)

    # Thread fork from main (multi-dep fallback)
    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_C"


@pytest.mark.asyncio
async def test_singleton_sole_child_reuses_predecessor_thread() -> None:
    """When B is the only step depending on A, B reuses A's thread directly
    (sole-child optimization — no checkpoint copy)."""
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
    state = LoopState(
        goal="Test goal",
        thread_id="logical-t",
        current_decision=decision,
        loop_messages=[],
        step_thread_ids={"A": "logical-t__step_A"},
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_b,
        "logical-t",
        loop_state=state,
    )

    # Sole-child reuse: B's CoreAgent runs under A's thread, no rename/copy.
    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_A"
    assert state.step_thread_ids.get("B") == "logical-t__step_A"
    assert state.thread_fork_sources.get("logical-t__step_A") == "logical-t__step_A"


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

    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t__step_solo"
    assert state.thread_fork_sources.get("logical-t__step_solo") == "logical-t"


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

    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t"


@pytest.mark.asyncio
async def test_multi_dep_respects_plan_ledger_max_messages_cap() -> None:
    """Multi-dep predecessor injection respects plan_ledger_max_messages cap."""
    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    cfg = MagicMock()
    cfg.agent.loop.plan_prompt_ledger.plan_ledger_max_messages = 3
    cfg.agent.loop.limits.max_parallel_tools = 5

    step_c = StepAction(
        id="C",
        description="consume",
        expected_output="o",
        dependencies=["A", "B"],  # Multi-dep
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
    executor = Executor(mock_agent, config=cfg, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step_c,
        "logical-t",
        loop_state=state,
    )

    messages = _astream_messages(mock_agent)
    # Should have up to cap predecessor messages + execute envelope
    assert len(messages) <= 4  # cap=3 predecessors + 1 envelope


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

    cfg = mock_agent.astream.call_args.kwargs["config"]["configurable"]
    assert cfg["thread_id"] == "logical-t"


@pytest.mark.asyncio
async def test_multi_dep_injection_logs_threadfork(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Multi-dep steps log ThreadFork message injection."""
    caplog.set_level(logging.INFO)

    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step_c = StepAction(
        id="C",
        description="third",
        expected_output="o3",
        dependencies=["A", "B"],  # Multi-dep triggers injection
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

    assert "[ThreadFork]" in caplog.text
    assert "multi-dep" in caplog.text or "injected" in caplog.text


@pytest.mark.asyncio
async def test_fork_copies_main_thread_into_step_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-deps step forks from main into a fresh ``__step_<id>`` namespace.

    The copy goes through ``copy_thread_via_public_api`` (in-house helper)
    because no LangGraph saver implements ``acopy_thread``.
    """
    from soothe.foundation.loop.engine import thread_fork_manager as tfm_mod

    copy_calls: list[tuple[str, str]] = []

    async def _fake_copy(saver: Any, source: str, target: str) -> int:
        copy_calls.append((source, target))
        return 0  # main has no checkpoints in this test fixture

    monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

    mock_agent = _make_mock_agent()
    mock_checkpointer = _make_mock_checkpointer()

    step = StepAction(id="test-step", description="test", expected_output="o")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(
        goal="g",
        thread_id="main-thread",
        current_decision=decision,
        loop_messages=[],
    )
    executor = Executor(mock_agent, checkpointer=mock_checkpointer)

    await executor._execute_step_collecting_events(
        step,
        "main-thread",
        loop_state=state,
    )

    # Fork from main into __step_ namespace (parallel-safe isolation).
    assert ("main-thread", "main-thread__step_test-step") in copy_calls
