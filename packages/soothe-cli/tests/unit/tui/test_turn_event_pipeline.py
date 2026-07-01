"""Tests for TUI turn stream pipeline and background preparation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from soothe_cli.runtime.state.session_stats import TurnEventStats, TurnLatencyStats
from soothe_cli.runtime.turn.pipeline import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    TurnApplyBatcher,
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

    state = TurnPrepareState(
        ev_stats=TurnEventStats(),
        presentation=PresentationEngine(),
    )
    assert prepare_turn_chunk(state, ((), "updates", {"model": {}})) is None
    assert state.ev_stats.filtered_early == 1
    prepared = prepare_turn_chunk(state, ((), "messages", (AIMessage(content="hi"), {})))
    assert prepared is not None
    assert prepared.mode == "messages"


def test_loop_assistant_output_message_gets_high_priority() -> None:
    """`plan_direct` / `goal_completion` text chunks must run at HIGH priority.

    Loop-tagged assistant output is interleaved with high-priority loop progress
    events (e.g. `plan_decision`, `step_started`). With default LOW priority the
    text card lands behind the step card even though the daemon emitted it first.
    Regression for: 'I will complete this...' appearing after the step card.
    """
    from soothe.foundation.sloop.utils.messages import LoopAIMessage

    from soothe_cli.runtime.presentation.engine import PresentationEngine

    state = TurnPrepareState(
        ev_stats=TurnEventStats(),
        presentation=PresentationEngine(),
    )

    plan_direct_msg = LoopAIMessage(
        content="I will complete this goal directly: read file",
        thread_id="t",
        iteration=0,
        phase="plan_direct",
    )
    prepared = prepare_turn_chunk(state, ((), "messages", (plan_direct_msg, {})))
    assert prepared is not None
    assert prepared.priority == PRIORITY_HIGH

    # Plain assistant text (no loop phase tag) stays LOW so it can't preempt
    # tool / progress events.
    plain = prepare_turn_chunk(state, ((), "messages", (AIMessage(content="hi"), {})))
    assert plain is not None
    assert plain.priority == PRIORITY_LOW


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


def test_turn_apply_batcher_flushes_on_high_priority() -> None:
    """IG-534 §3.4: HIGH priority chunks bypass batch accumulation."""
    batcher: TurnApplyBatcher[str] = TurnApplyBatcher(max_batch_size=10, max_batch_delay_ms=50)

    @dataclass
    class _Plan:
        label: str
        priority: int = PRIORITY_LOW

    assert batcher.add(_Plan("low")) is False
    assert batcher.add(_Plan("high", priority=PRIORITY_HIGH)) is True
    batch = batcher.flush()
    assert [p.label for p in batch] == ["low", "high"]


@pytest.mark.asyncio
async def test_run_turn_pipeline_records_latency_stats() -> None:
    """IG-534 Phase 3: pipeline records time-to-first-chunk latency."""
    from soothe.foundation.sloop.utils.messages import LoopAIMessage

    latency = TurnLatencyStats(turn_start_monotonic=time.monotonic())
    applied: list[str] = []

    @dataclass
    class _Plan:
        mode: str
        normalized_message: Any
        skip: bool = False

    async def _source() -> Any:
        yield (
            (),
            "messages",
            (
                LoopAIMessage(
                    content="hi",
                    thread_id="t",
                    iteration=0,
                    phase="goal_completion",
                ),
                {},
            ),
        )

    def _process(raw: Any) -> _Plan:
        _ns, mode, data = raw
        msg, _meta = data
        return _Plan(mode=mode, normalized_message=msg)

    async def _apply(_prepared: _Plan) -> None:
        applied.append("applied")

    await run_turn_pipeline(_source(), _process, _apply, latency_stats=latency)

    assert applied == ["applied"]
    assert latency.time_to_first_chunk_ms is not None
    assert latency.synthesis_visible_ms is not None
    assert latency.goal_completion_applied is True
