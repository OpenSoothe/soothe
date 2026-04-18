"""Regression tests for LangGraph stream polling (IG-193)."""

from __future__ import annotations

import asyncio

import pytest

from soothe.core.runner._runner_phases import _STREAM_POLL_INTERVAL_S, _await_next_astream_chunk


@pytest.mark.asyncio
async def test_await_next_astream_chunk_accepts_gaps_longer_than_poll_interval() -> None:
    """Slow sources must not lose chunks: wait_for+anext used to cancel pending reads."""

    async def slow_stream() -> None:
        await asyncio.sleep(_STREAM_POLL_INTERVAL_S + 0.15)
        yield ((), "updates", {"middleware": True})
        await asyncio.sleep(_STREAM_POLL_INTERVAL_S + 0.15)
        yield ((), "messages", ("assistant", "done"))

    agen = slow_stream()
    it = agen.__aiter__()

    first = await _await_next_astream_chunk(it)
    assert first == ((), "updates", {"middleware": True})

    second = await _await_next_astream_chunk(it)
    assert second == ((), "messages", ("assistant", "done"))

    with pytest.raises(StopAsyncIteration):
        await _await_next_astream_chunk(it)
