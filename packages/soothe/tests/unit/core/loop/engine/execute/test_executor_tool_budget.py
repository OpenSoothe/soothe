"""Executor per-step tool call budget wiring."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from soothe.config.constants import DEFAULT_MAX_TOOL_CALLS_PER_STEP
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.protocol import LoopStateView
from soothe.sloop.engine.execute.executor import (
    Executor,
    _ActStreamBudget,
)
from soothe.sloop.engine.execute.graph_interrupt import DispatchTimeoutError
from soothe.sloop.relay.inbox import RelayInbox
from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction, StepExecutionRecord


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_step() -> StepAction:
    return StepAction(
        id="s0",
        description="Run tools",
        expected_output="ok",
        dependencies=[],
    )


@pytest.mark.asyncio
async def test_stream_stops_after_tool_budget_with_partial_outcomes() -> None:
    budget = _ActStreamBudget(max_tool_calls_per_step=2)
    chunks: list = [
        ((), "messages", (ToolMessage(content="alpha", tool_call_id="1", name="grep"), {})),
        ((), "messages", (ToolMessage(content="beta", tool_call_id="2", name="grep"), {})),
        ((), "messages", (ToolMessage(content="gamma", tool_call_id="3", name="grep"), {})),
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce())
    rows = [
        r
        async for r in ex._stream_and_collect(fake_stream(), budget=budget, step_id="s0")
        if r.output is not None
    ]

    assert len(rows) == 1
    final = rows[0]
    assert final.main_tool_count == 2
    assert budget.hit_tool_budget is True
    assert "alpha" in (final.output or "") and "beta" in (final.output or "")
    assert "gamma" not in (final.output or "")
    assert len(final.outcomes) == 2


def test_default_max_tool_calls_per_step_is_500() -> None:
    assert DEFAULT_MAX_TOOL_CALLS_PER_STEP == 500
    assert (
        Executor(
            MagicMock(), max_parallel_steps=1, context_engine=_make_ce()
        )._max_tool_calls_per_step()
        == 500
    )


def test_max_tool_calls_per_step_reads_loop_config() -> None:
    config = MagicMock()
    config.agent.loop.max_tool_calls_per_step = 42
    ex = Executor(
        MagicMock(),
        max_parallel_steps=1,
        config=config,
        context_engine=_make_ce(),
    )
    assert ex._max_tool_calls_per_step() == 42


def _make_mock_agent(chunks: list) -> MagicMock:
    async def fake_execution_astream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        for c in chunks:
            yield c

    agent = MagicMock()
    agent.execution_astream = MagicMock(side_effect=fake_execution_astream)
    agent.execution_aget_state = AsyncMock(return_value=MagicMock())
    agent.aget_state = AsyncMock(return_value=MagicMock())
    return agent


@pytest.mark.asyncio
async def test_execute_parallel_step_returns_partial_on_tool_budget() -> None:
    tool_msgs = [
        (
            (),
            "messages",
            (ToolMessage(content=f"out-{i}", tool_call_id=str(i), name="run_command"), {}),
        )
        for i in range(DEFAULT_MAX_TOOL_CALLS_PER_STEP + 5)
    ]
    agent = _make_mock_agent(tool_msgs)

    ce = _make_ce()
    ex = Executor(agent, max_parallel_steps=1, config=None, context_engine=ce)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()

    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )
    out = [item async for item in ex.execute(decision, state)]

    results = [x for x in out if isinstance(x, StepExecutionRecord)]
    assert len(results) == 1
    sr = results[0]
    assert sr.hit_tool_budget is True
    assert sr.tool_call_count == DEFAULT_MAX_TOOL_CALLS_PER_STEP
    assert sr.success is True
    assert state.last_wave_hit_tool_budget is True
    preview = sr.outcome.get("wave_join_preview") or sr.outcome.get("output_summary") or ""
    if isinstance(preview, dict):
        preview = str(preview.get("first", ""))
    assert "out-0" in str(preview)
    ledger_ai = [m for m in ce.ledger.get_messages() if getattr(m, "step_id", None) == "s0"][-1]
    assert "Step execution failed" not in ledger_ai.content


@pytest.mark.asyncio
async def test_stream_collect_exposes_execution_metrics() -> None:
    budget = _ActStreamBudget(max_tool_calls_per_step=8)
    chunks = [
        (
            (),
            "messages",
            (ToolMessage(content="x.py:12:needle", tool_call_id="1", name="grep"), {}),
        ),
        (
            (),
            "messages",
            (
                ToolMessage(
                    content="1|line one\n2|line two",
                    tool_call_id="2",
                    name="read_file",
                ),
                {},
            ),
        ),
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce())
    rows = [
        r
        async for r in ex._stream_and_collect(fake_stream(), budget=budget, step_id="s0")
        if r.output is not None
    ]
    assert len(rows) == 1
    final = rows[0]
    assert final.execution_metrics.get("search_calls_total") == 1
    assert final.execution_metrics.get("evidence_reads_total") == 1


@pytest.mark.asyncio
async def test_stream_collect_no_progress_watchdog_raises_timeout() -> None:
    config = MagicMock()
    config.agent.loop.dispatch_idle_seconds = 0.01
    config.agent.loop.max_tool_calls_per_step = 999

    async def fake_stream():
        yield ((), "custom", {"kind": "heartbeat"})
        await asyncio.sleep(0.03)
        yield ((), "custom", {"kind": "heartbeat"})

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce(), config=config)
    with pytest.raises(DispatchTimeoutError):
        async for _ in ex._stream_and_collect(
            fake_stream(),
            budget=_ActStreamBudget(max_tool_calls_per_step=10),
            step_id="s_watchdog",
        ):
            pass


@pytest.mark.asyncio
async def test_empty_stream_step_marks_failure_not_success() -> None:
    """A step that produces no chunks (model failure) must not be success=True.

    When MultiModelChatModel raises RuntimeError('all models in pool failed')
    and LangGraph swallows it, the stream ends with no chunks. The step must
    be marked failed, not 'completed successfully' — otherwise the DAG
    re-dispatches it indefinitely.
    """

    async def empty_stream():
        return
        yield  # make this a generator

    agent = _make_mock_agent([])
    ce = _make_ce()
    ex = Executor(agent, max_parallel_steps=1, config=None, context_engine=ce)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )
    out = [item async for item in ex.execute(decision, state)]
    results = [x for x in out if isinstance(x, StepExecutionRecord)]
    assert len(results) == 1
    sr = results[0]
    assert sr.success is False
    assert sr.error_type == "execution"
    assert "no output" in (sr.error or "").lower() or "model failure" in (sr.error or "").lower()


@pytest.mark.asyncio
async def test_redispatch_circuit_breaker_trips_after_max() -> None:
    """Progress-aware breaker: guided retry on deterministic stall, then fatal.

    Counter persists on LoopState across re-entries. A deterministic stall
    (same failure-mode signature) triggers a guided retry first and resets
    the count; a second identical stall after guidance trips fatally.
    """
    config = MagicMock()
    config.agent.loop.max_redispatch_per_step = 2
    config.agent.loop.context_window_limit = 100000
    config.agent.loop.execute_min_answer_chars = 50

    agent = _make_mock_agent([])
    ce = _make_ce()
    ex = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )
    # First dispatch: step fails (empty output), counter = 1
    out1 = [item async for item in ex.execute(decision, state)]
    results1 = [x for x in out1 if isinstance(x, StepExecutionRecord)]
    assert len(results1) == 1
    assert results1[0].success is False

    # Simulate graph re-entry: new Executor, same state
    ex2 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out2 = [item async for item in ex2.execute(decision, state)]
    results2 = [x for x in out2 if isinstance(x, StepExecutionRecord)]
    # Counter = 2 → still under limit (max=2), step is dispatched and fails again
    assert len(results2) == 1
    assert results2[0].success is False

    # Third dispatch: counter = 3 > max=2, but failure mode is repeating
    # (deterministic stall) and no guided retry yet → guided retry injected,
    # count reset, step dispatched again. Not a fatal trip.
    ex3 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out3 = [item async for item in ex3.execute(decision, state)]
    results3 = [x for x in out3 if isinstance(x, StepExecutionRecord)]
    assert len(results3) == 1
    assert results3[0].success is False
    # Guided retry was injected (not fatal); guidance message consumed.
    assert state.step_guided_retry_done.get(step.id) is True
    assert "circuit breaker" not in (results3[0].error or "").lower()

    # Fourth dispatch: count was reset to 1 by the guided retry, so this is
    # count = 2 (still under max=2). Step dispatched and fails again.
    ex4 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out4 = [item async for item in ex4.execute(decision, state)]
    results4 = [x for x in out4 if isinstance(x, StepExecutionRecord)]
    assert len(results4) == 1
    assert results4[0].success is False

    # Fifth dispatch: count = 3 > max=2, guided retry already done →
    # circuit breaker trips fatally now.
    ex5 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out5 = [item async for item in ex5.execute(decision, state)]
    results5 = [x for x in out5 if isinstance(x, StepExecutionRecord)]
    assert len(results5) == 1
    assert results5[0].success is False
    assert results5[0].error_type == "fatal"
    assert "circuit breaker" in (results5[0].error or "").lower()


@pytest.mark.asyncio
async def test_consecutive_empty_completion_watchdog_force_fails() -> None:
    """After N consecutive empty completions, the watchdog force-fails the step.

    This catches model-failure loops where the model produces a few truncated
    tokens (not enough for meaningful output) but no tool calls, and the step
    is marked success=True because no tool *failed*.
    """
    from langchain_core.messages import AIMessageChunk

    config = MagicMock()
    config.agent.loop.max_consecutive_empty_completions = 2
    config.agent.loop.execute_min_answer_chars = 50
    config.agent.loop.context_window_limit = 100000
    config.agent.loop.max_redispatch_per_step = 99  # don't trip re-dispatch breaker

    # Stream that produces a short chunk (20-49 chars) with 0 tool calls.
    # This passes the has_meaningful_output guard (output >= min_answer_chars=20)
    # but the consecutive-empty watchdog catches the repeated no-progress pattern
    # (output < _EMPTY_OUTPUT_MIN_CHARS=50, main_tools=0).
    tiny_chunk = (
        (),
        "messages",
        (AIMessageChunk(content="Let me verify the current state."), {}),
    )

    agent = _make_mock_agent([tiny_chunk])
    ce = _make_ce()
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )

    # First dispatch: empty completion count = 1 (under threshold)
    ex1 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out1 = [item async for item in ex1.execute(decision, state)]
    r1 = [x for x in out1 if isinstance(x, StepExecutionRecord)]
    assert len(r1) == 1
    # First time might be failure (empty output guard) or success (if output >= threshold)
    # but the consecutive-empty counter should be tracking

    # Second dispatch: empty completion count = 2 → force-fail
    ex2 = Executor(agent, max_parallel_steps=1, config=config, context_engine=ce)
    out2 = [item async for item in ex2.execute(decision, state)]
    r2 = [x for x in out2 if isinstance(x, StepExecutionRecord)]
    assert len(r2) == 1
    # After 2 consecutive empties, the watchdog force-fails
    assert r2[0].success is False
    assert r2[0].error_type == "fatal"
    assert "consecutive" in (r2[0].error or "").lower()


# ---------------------------------------------------------------------------
# Progress-aware breaker: interrupt-resumed dispatches (f07f regression)
# ---------------------------------------------------------------------------


class _InterruptStubAgent:
    """CoreAgent stand-in: yields scripted chunks, then raises a
    GraphInterrupt carrying a tool-approval Interrupt (the pause shape)."""

    def __init__(self) -> None:
        self._scripts: list[tuple[list[Any], Any]] = []

    def queue(self, chunks: list[Any], *, interrupt: Any = None) -> None:
        self._scripts.append((chunks, interrupt))

    def execution_astream(self, *_a: object, **_k: object) -> Any:
        chunks, interrupt = self._scripts.pop(0)

        async def _gen() -> Any:
            for c in chunks:
                yield c
            if interrupt is not None:
                raise GraphInterrupt((interrupt,))

        return _gen()

    async def aget_state(self, config: Any = None) -> Any:
        return SimpleNamespace(interrupts=(), tasks=(), values={})

    async def execution_aget_state(self, config: Any = None) -> Any:
        return await self.aget_state(config)

    @property
    def can_read_graph_state(self) -> bool:
        return True


def _pause_view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="build feature X",
        user_request="build feature X",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _tool_approval_interrupt(interrupt_id: str) -> Any:
    return Interrupt(
        value={"action_requests": [{"name": "run_command", "args": {"command": "rm -rf /tmp/x"}}]},
        id=interrupt_id,
    )


def _ok_tool_chunk() -> tuple:
    return (
        (),
        "messages",
        (ToolMessage(content="Folder created.", tool_call_id="c1", name="run_command"), {}),
    )


def _failing_tool_chunk() -> tuple:
    return (
        (),
        "messages",
        (
            ToolMessage(
                content="Not a file: /tmp/x",
                tool_call_id="c1",
                name="delete",
                status="error",
            ),
            {},
        ),
    )


def _make_pause_state() -> tuple[ContextEngine, LoopState, StepAction, AgentDecision]:
    ce = _make_ce()
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )
    return ce, state, step, decision


def _pause_config(max_redispatch: int) -> MagicMock:
    config = MagicMock()
    config.agent.loop.max_redispatch_per_step = max_redispatch
    config.agent.loop.max_tool_calls_per_step = 99
    config.agent.loop.context_window_limit = 100000
    config.agent.loop.execute_min_answer_chars = 50
    config.agent.loop.dispatch_idle_seconds = 60.0
    config.agent.loop.max_consecutive_empty_completions = 99
    return config


async def _run_paused_dispatch(
    agent: _InterruptStubAgent,
    *,
    config: Any,
    ce: ContextEngine,
    capture: RelayInbox,
    state: LoopState,
    decision: AgentDecision,
) -> list[StepExecutionRecord]:
    ex = Executor(
        agent,
        max_parallel_steps=1,
        config=config,
        context_engine=ce,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_pause_view(),
    )
    out = [item async for item in ex.execute(decision, state)]
    return [x for x in out if isinstance(x, StepExecutionRecord)]


@pytest.mark.asyncio
async def test_interrupt_resume_with_tool_progress_resets_redispatch_count() -> None:
    """f07f regression: a dispatch paused by tool approval after a successful
    tool call made progress — the breaker budget must reset, not accumulate."""
    config = _pause_config(max_redispatch=2)

    agent = _InterruptStubAgent()
    capture = RelayInbox()
    ce, state, step, decision = _make_pause_state()

    # Five dispatch rounds — far past max_redispatch=2. Each dispatch runs a
    # successful tool, then pauses; paused steps yield no completion record,
    # so the invariant under test is the counter state.
    for i in range(5):
        agent.queue([_ok_tool_chunk()], interrupt=_tool_approval_interrupt(f"i{i}"))
        records = await _run_paused_dispatch(
            agent, config=config, ce=ce, capture=capture, state=state, decision=decision
        )
        assert all("circuit breaker" not in (r.error or "").lower() for r in records)
        # Productive pause reset the breaker budget.
        assert state.step_dispatch_counts.get(step.id, 0) == 0
        assert step.id not in state.step_failure_modes
        # The step actually paused: the relay holds the approval request.
        assert capture.dequeue() is not None


@pytest.mark.asyncio
async def test_unproductive_pause_gets_guided_retry_then_trips() -> None:
    """Pauses whose only work was a failing tool attempt keep the count; the
    breaker injects a guided retry first, then trips fatally on a stall."""
    config = _pause_config(max_redispatch=2)

    agent = _InterruptStubAgent()
    capture = RelayInbox()
    ce, state, step, decision = _make_pause_state()

    # Rounds 1-2: count climbs (1, 2). Round 3: count=3 > max=2 with a
    # repeating failure mode → guided retry, count reset to 1, dispatched.
    # Round 4: count=2, dispatched. Round 5: count=3 > max, guided retry
    # already done → fatal trip (no dispatch).
    expected_counts = {1: 1, 2: 2, 3: 1, 4: 2}
    for round_no in range(1, 6):
        if round_no <= 4:
            agent.queue([_failing_tool_chunk()], interrupt=_tool_approval_interrupt(f"i{round_no}"))
        records = await _run_paused_dispatch(
            agent, config=config, ce=ce, capture=capture, state=state, decision=decision
        )
        if round_no <= 4:
            # Paused dispatch: no completion record, count kept (no progress).
            capture.dequeue()
            assert records == []
            assert state.step_dispatch_counts.get(step.id) == expected_counts[round_no]
            assert step.id in state.step_failure_modes
        if round_no == 3:
            # Guided retry was injected instead of a fatal trip.
            assert state.step_guided_retry_done.get(step.id) is True
        if round_no == 5:
            assert len(records) == 1
            assert records[0].success is False
            assert records[0].error_type == "fatal"
            assert "circuit breaker" in (records[0].error or "").lower()


@pytest.mark.asyncio
async def test_step_success_clears_redispatch_counters() -> None:
    """A dispatch that completes the step clears all breaker counters."""
    agent = _InterruptStubAgent()
    capture = RelayInbox()
    ce, state, step, decision = _make_pause_state()

    # Dispatch 1: empty stream → failure; count and failure mode recorded.
    agent.queue([])
    records = await _run_paused_dispatch(
        agent, config=None, ce=ce, capture=capture, state=state, decision=decision
    )
    assert len(records) == 1
    assert records[0].success is False
    assert state.step_dispatch_counts.get(step.id) == 1
    assert step.id in state.step_failure_modes

    # Dispatch 2: successful tool, no interrupt → step completes; counters cleared.
    agent.queue([_ok_tool_chunk()])
    records = await _run_paused_dispatch(
        agent, config=None, ce=ce, capture=capture, state=state, decision=decision
    )
    assert len(records) == 1
    assert records[0].success is True
    assert step.id not in state.step_dispatch_counts
    assert step.id not in state.step_failure_modes
    assert step.id not in state.step_guided_retry_done
