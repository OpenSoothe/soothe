"""Tests for QueryEngine batched stream broadcast (IG-535 Opt 3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from soothe_daemon.query.engine import QueryEngine


@pytest.mark.asyncio
async def test_broadcast_coalescer_outputs_batches_multiple_events() -> None:
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    daemon = SimpleNamespace(
        _broadcast=_broadcast,
        _loop_broadcast_budget=None,
        _card_manager=None,
    )
    engine = QueryEngine(daemon)

    outputs = [
        ((), "messages", ({"content": "a", "chunk_position": "last"}, {})),
        ((), "custom", {"kind": "event", "type": "tool_call", "data": {}}),
    ]
    await engine._broadcast_coalescer_outputs("loop-batch", outputs)

    assert len(broadcasts) == 1
    frame = broadcasts[0]
    assert frame["type"] == "event_batch"
    assert frame["loop_id"] == "loop-batch"
    assert len(frame["events"]) == 2


@pytest.mark.asyncio
async def test_broadcast_coalescer_outputs_single_event_not_batched() -> None:
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    daemon = SimpleNamespace(
        _broadcast=_broadcast,
        _loop_broadcast_budget=None,
        _card_manager=None,
    )
    engine = QueryEngine(daemon)

    outputs = [
        ((), "messages", ({"content": "only", "chunk_position": "last"}, {})),
    ]
    await engine._broadcast_coalescer_outputs("loop-one", outputs)

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "event"
