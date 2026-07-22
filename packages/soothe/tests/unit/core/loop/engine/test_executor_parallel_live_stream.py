"""Parallel execute forwards stream events while steps are still running."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.executor import Executor, StreamEvent, _ExecuteStepResult
from soothe.sloop.state.schemas import LoopState, StepAction, StepResult


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


@pytest.mark.asyncio
async def test_execute_parallel_yields_stream_events_before_all_steps_finish() -> None:
    """Stream chunks must reach the consumer during the wave, not only after gather."""
    fast_event: StreamEvent = (("tools:fast",), "messages", (MagicMock(), {}))
    slow_event: StreamEvent = (("tools:slow",), "messages", (MagicMock(), {}))

    async def fake_collect(
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        live_event_queue: asyncio.Queue[Any] | None = None,
        **kwargs: Any,
    ) -> _ExecuteStepResult:
        del thread_id, workspace, kwargs
        if step.id == "slow":
            await asyncio.sleep(0.25)
        else:
            await asyncio.sleep(0.03)
        event = slow_event if step.id == "slow" else fast_event
        if live_event_queue is not None:
            live_event_queue.put_nowait(event)
        result = StepResult(
            step_id=step.id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t-par",
            tool_call_count=1,
        )
        return _ExecuteStepResult(events=[event], step_result=result)

    executor = Executor(MagicMock(), max_parallel_steps=4, context_engine=_make_ce())
    executor._execute_step_collecting_events = fake_collect  # type: ignore[method-assign]

    state = LoopState(goal="g", thread_id="t-par", iteration=0, max_iterations=4)
    steps = [
        StepAction(id="fast", description="fast step"),
        StepAction(id="slow", description="slow step"),
    ]

    seen: list[Any] = []
    first_tool_at: float | None = None
    all_done_at: float | None = None
    loop = asyncio.get_running_loop()
    start = loop.time()

    async for item in executor._execute_parallel(steps, state):
        seen.append(item)
        if first_tool_at is None and isinstance(item, tuple) and item[1] == "messages":
            first_tool_at = loop.time() - start
        if all_done_at is None and len([x for x in seen if isinstance(x, StepResult)]) == len(
            steps
        ):
            all_done_at = loop.time() - start

    assert first_tool_at is not None
    assert all_done_at is not None
    assert first_tool_at < all_done_at - 0.08
    assert len([x for x in seen if isinstance(x, tuple) and len(x) == 3]) == 2
    step_results = [x for x in seen if isinstance(x, StepResult)]
    assert len(step_results) == 2
    assert {r.step_id for r in step_results} == {"fast", "slow"}


@pytest.mark.asyncio
async def test_execute_parallel_ledger_uses_step_id_when_completion_order_differs() -> None:
    """Ledger rows align to plan step order via step_id, not completion order."""
    order: list[str] = []

    async def fake_collect(
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        live_event_queue: asyncio.Queue[Any] | None = None,
        **kwargs: Any,
    ) -> _ExecuteStepResult:
        del thread_id, workspace, live_event_queue, kwargs
        if step.id == "first":
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(0.02)
        order.append(step.id)
        result = StepResult(
            step_id=step.id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t-order",
            tool_call_count=0,
        )
        return _ExecuteStepResult(step_result=result)

    executor = Executor(MagicMock(), max_parallel_steps=4, context_engine=_make_ce())
    executor._execute_step_collecting_events = fake_collect  # type: ignore[method-assign]

    ce = _make_ce()
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state = LoopState(goal="g", thread_id="t-order", iteration=0, max_iterations=4)
    state.bind_ce(ce, goal.id)
    executor._context_engine = ce

    steps = [
        StepAction(id="first", description="slow first in plan"),
        StepAction(id="second", description="fast second in plan"),
    ]

    async for _ in executor._execute_parallel(steps, state):
        pass

    assert order[0] == "second"
    # Check CE ledger directly
    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 4
    assert ledger_msgs[0].content.startswith("EXECUTION TASK:\n")
    assert "slow first in plan" in ledger_msgs[0].content
    assert getattr(ledger_msgs[0], "step_id", None) == "first"
    assert ledger_msgs[2].content.startswith("EXECUTION TASK:\n")
    assert "fast second in plan" in ledger_msgs[2].content
    assert getattr(ledger_msgs[2], "step_id", None) == "second"
