"""Stream event fan-out and heartbeat wire-path tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.engine.graph_interrupt import _DEFAULT_DISPATCH_TIMEOUT_S
from soothe.foundation.sloop.engine.step_wave_types import (
    StreamEvent,
    _append_parallel_stream_event,
)


def test_append_parallel_stream_event_skips_events_list_when_live_queue() -> None:
    """Live parallel execute must not duplicate wire events on the step result."""
    events: list[StreamEvent] = []
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    wire: StreamEvent = ((), "custom", {"type": "tool_call_update"})

    _append_parallel_stream_event(events, wire, queue)

    assert events == []
    assert queue.get_nowait() == wire


def test_append_parallel_stream_event_retains_events_without_live_queue() -> None:
    """Direct callers without a live queue still accumulate events on the result."""
    events: list[StreamEvent] = []
    wire: StreamEvent = ((), "custom", {"type": "tool_call_update"})

    _append_parallel_stream_event(events, wire, None)

    assert events == [wire]


@pytest.mark.asyncio
async def test_stream_and_collect_forwards_step_heartbeat_custom_event() -> None:
    """Custom heartbeat chunks from interrupt_resume reach wire consumers."""
    heartbeat: StreamEvent = ((), "custom", {"type": "step_heartbeat", "step_id": "S1"})

    async def fake_stream() -> AsyncIterator[StreamEvent]:
        yield heartbeat

    executor = Executor(MagicMock())
    wire_rows = [
        row
        async for row in executor._stream_and_collect(fake_stream(), step_id="S1")
        if row.event is not None
    ]

    assert wire_rows[0].event == heartbeat


@pytest.mark.asyncio
async def test_interrupt_resume_emits_raw_tuple_on_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IG-549: heartbeat must be a LangGraph tuple for ``_stream_and_collect`` to wrap it."""
    monkeypatch.setattr(
        "soothe.foundation.sloop.engine.graph_interrupt._STREAM_HEARTBEAT_INTERVAL_S",
        0.15,
    )

    async def blocking_stream() -> AsyncIterator[str]:
        await asyncio.sleep(5.0)
        if False:  # pragma: no cover
            yield "never"

    mock_agent = MagicMock()
    mock_agent.execution_astream = MagicMock(return_value=blocking_stream())
    executor = Executor(mock_agent)

    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        step_id="HB-01",
    )

    first = await asyncio.wait_for(anext(stream), timeout=1.0)
    assert isinstance(first, tuple)
    assert first[0] == ()
    assert first[1] == "custom"
    assert first[2]["type"] == "step_heartbeat"
    assert first[2]["step_id"] == "HB-01"

    await stream.aclose()


@pytest.mark.asyncio
async def test_interrupt_resume_sets_graph_dispatch_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph stream reader should enforce dispatch watchdog by default."""

    class _FakeReader:
        def __init__(
            self,
            _chunk_iter: AsyncIterator[str],
            *,
            dispatch_timeout: float | None = None,
            step_id: str | None = None,
            heartbeat_interval: float | None = None,
        ) -> None:
            _ = step_id, heartbeat_interval
            self.dispatch_timeout = dispatch_timeout

        async def read_next(self) -> str:
            raise StopAsyncIteration

        async def cancel(self) -> None:
            return None

    captured: dict[str, float | None] = {}

    def _reader_factory(*args: object, **kwargs: object) -> _FakeReader:
        reader = _FakeReader(*args, **kwargs)
        captured["dispatch_timeout"] = reader.dispatch_timeout
        return reader

    monkeypatch.setattr(
        "soothe.foundation.sloop.engine.executor.GraphStreamChunkReader",
        _reader_factory,
    )

    async def empty_stream() -> AsyncIterator[str]:
        if False:  # pragma: no cover
            yield "never"

    mock_agent = MagicMock()
    mock_agent.execution_astream = MagicMock(return_value=empty_stream())
    mock_agent.can_read_graph_state = False
    executor = Executor(mock_agent)

    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        step_id="S-01",
    )
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    assert captured["dispatch_timeout"] == _DEFAULT_DISPATCH_TIMEOUT_S
