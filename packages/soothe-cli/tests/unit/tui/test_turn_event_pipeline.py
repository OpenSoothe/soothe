"""Tests for TUI turn stream pipeline and background preparation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from soothe_cli.runtime.turn.pipeline import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    TurnEventPipeline,
    run_turn_pipeline,
)
from soothe_cli.runtime.turn.prepare import TurnPrepareState, prepare_turn_chunk


@pytest.mark.asyncio
async def test_run_turn_pipeline_processes_chunks_in_order() -> None:
    """Reader, processor thread, and applier preserve chunk order for same priority."""
    received: list[Any] = []

    async def _source() -> Any:
        for item in [
            ("ns", "custom", {"type": "soothe.test.event"}),
            ("", "messages", (AIMessage(content="hi"), {})),
        ]:
            yield item

    def _process(raw: Any) -> tuple[Any, ...]:
        return tuple(raw)

    async def _apply(prepared: tuple[Any, ...]) -> None:
        received.append(prepared)

    await run_turn_pipeline(_source(), _process, _apply)

    assert len(received) == 2
    assert received[0][1] == "custom"


def test_priority_queue_orders_high_before_low() -> None:
    """Outbound priority queue drains HIGH before LOW when both are buffered."""
    import queue as std_queue

    pq: std_queue.PriorityQueue[tuple[int, int, str]] = std_queue.PriorityQueue()
    pq.put((PRIORITY_LOW, 0, "low"))
    pq.put((PRIORITY_HIGH, 1, "high"))
    assert pq.get()[2] == "high"
    assert pq.get()[2] == "low"


@pytest.mark.asyncio
async def test_pipeline_drains_without_deadlock() -> None:
    """Processor thread and applier coroutine both complete (regression: no future.result deadlock)."""

    @dataclass
    class _Plan:
        label: str
        priority: int = PRIORITY_LOW

    received: list[str] = []

    async def _source() -> Any:
        yield "low"
        yield "high"

    def _process(raw: Any) -> _Plan:
        if raw == "high":
            return _Plan("high", priority=PRIORITY_HIGH)
        return _Plan("low", priority=PRIORITY_LOW)

    async def _apply(prepared: _Plan) -> None:
        received.append(prepared.label)

    await run_turn_pipeline(_source(), _process, _apply)

    assert sorted(received) == ["high", "low"]


def test_prepare_turn_chunk_skips_invisible_custom_events() -> None:
    """Custom events below the active verbosity tier are dropped in prepare."""
    from soothe_cli.runtime.presentation.engine import PresentationEngine
    from soothe_cli.runtime.state.session_stats import TurnEventStats

    state = TurnPrepareState(
        ev_stats=TurnEventStats(),
        presentation=PresentationEngine(),
    )
    prepared = prepare_turn_chunk(
        state,
        (
            ("sub",),
            "custom",
            {"type": "soothe.debug.internal.trace", "message": "noise"},
        ),
    )
    assert prepared is not None
    assert prepared.skip is True


def test_prepare_turn_chunk_skips_noop_updates_only() -> None:
    from soothe_cli.runtime.presentation.engine import PresentationEngine
    from soothe_cli.runtime.state.session_stats import TurnEventStats

    state = TurnPrepareState(
        ev_stats=TurnEventStats(),
        presentation=PresentationEngine(),
    )
    assert prepare_turn_chunk(state, ((), "updates", {"model": {}})) is None
    assert state.ev_stats.filtered_early == 1
    prepared = prepare_turn_chunk(state, ((), "messages", (AIMessage(content="hi"), {})))
    assert prepared is not None
    assert prepared.mode == "messages"


@pytest.mark.asyncio
async def test_pipeline_propagates_processor_errors() -> None:
    """Processor exceptions surface to the applier coroutine."""
    loop = asyncio.get_running_loop()
    pipeline: TurnEventPipeline[None] = TurnEventPipeline(loop)

    def _boom(_raw: Any) -> None:
        raise ValueError("processor failed")

    pipeline.start_processor(_boom)

    await asyncio.to_thread(pipeline._inbound.put, ("", "updates", {}))

    with pytest.raises(ValueError, match="processor failed"):
        async for _item in pipeline.iter_prepared():
            pass

    pipeline.shutdown()
