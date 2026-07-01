"""Priority-aware outbound queue drop policy for the TUI turn pipeline."""

from __future__ import annotations

import asyncio
import queue
from dataclasses import dataclass

import pytest

from soothe_cli.runtime.turn.pipeline import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    TurnEventPipeline,
)


@dataclass
class _Prepared:
    label: str
    priority: int = PRIORITY_LOW


@pytest.mark.asyncio
async def test_outbound_queue_evicts_low_priority_for_step_completed() -> None:
    """step_completed must not be dropped when the outbound queue is full."""
    loop = asyncio.get_running_loop()
    pipeline: TurnEventPipeline[_Prepared] = TurnEventPipeline(loop, outbound_maxsize=4)

    for i in range(4):
        pipeline._put_outbound(PRIORITY_LOW, _Prepared(f"text-{i}"))

    pipeline._put_outbound(
        PRIORITY_CRITICAL,
        _Prepared("step-completed", priority=PRIORITY_CRITICAL),
    )

    items: list[_Prepared] = []
    while True:
        try:
            _priority, _seq, item = pipeline._outbound.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, _Prepared):
            items.append(item)

    labels = [item.label for item in items]
    assert "step-completed" in labels
    assert pipeline._outbound_dropped >= 1
    assert len(labels) == 4


@pytest.mark.asyncio
async def test_outbound_queue_drops_incoming_low_when_only_high_buffered() -> None:
    """LOW-priority chunks may be dropped when the queue holds only progress events."""
    loop = asyncio.get_running_loop()
    pipeline: TurnEventPipeline[_Prepared] = TurnEventPipeline(loop, outbound_maxsize=2)

    pipeline._put_outbound(PRIORITY_HIGH, _Prepared("tool-wire-1"))
    pipeline._put_outbound(PRIORITY_HIGH, _Prepared("tool-wire-2"))
    pipeline._put_outbound(PRIORITY_LOW, _Prepared("streaming-text"))

    items: list[_Prepared] = []
    while True:
        try:
            _priority, _seq, item = pipeline._outbound.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, _Prepared):
            items.append(item)

    assert [item.label for item in items] == ["tool-wire-1", "tool-wire-2"]
    assert pipeline._outbound_dropped == 1


def test_evict_outbound_drop_candidate_prefers_lowest_priority() -> None:
    loop = asyncio.new_event_loop()
    pipeline: TurnEventPipeline[_Prepared] = TurnEventPipeline(loop, outbound_maxsize=3)
    pipeline._put_outbound(PRIORITY_HIGH, _Prepared("high"))
    pipeline._put_outbound(PRIORITY_NORMAL, _Prepared("normal"))
    pipeline._put_outbound(PRIORITY_LOW, _Prepared("low"))

    assert pipeline._evict_outbound_drop_candidate(incoming_priority=PRIORITY_CRITICAL) is True

    remaining: list[str] = []
    while True:
        try:
            _priority, _seq, item = pipeline._outbound.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, _Prepared):
            remaining.append(item.label)

    assert remaining == ["high", "normal"]
    assert pipeline._outbound_dropped == 1
