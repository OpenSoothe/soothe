"""Tests for IG-429 ResponsePusher (zero poll-delay thread bridge)."""

from __future__ import annotations

import asyncio
import time

import pytest

from soothe_daemon.runner.response_bridge import ResponsePusher


@pytest.mark.asyncio
async def test_response_pusher_delivers_100_chunks_under_one_second() -> None:
    """Push path must not impose 50ms-per-chunk poll delay (100 chunks in <1s)."""
    loop = asyncio.get_running_loop()
    out: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    pusher = ResponsePusher(loop, out)

    async def producer() -> None:
        for i in range(100):
            pusher.push_from_worker("chunk", (("ns",), "messages", f"part-{i}"))

    async def consumer() -> None:
        for _ in range(100):
            msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
            assert msg_type == "chunk"
            assert payload is not None

    start = time.monotonic()
    await asyncio.gather(producer(), consumer())
    elapsed = time.monotonic() - start
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_response_pusher_maps_cancelled_to_error() -> None:
    loop = asyncio.get_running_loop()
    out: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    pusher = ResponsePusher(loop, out)

    pusher.push_from_worker("cancelled")
    await asyncio.sleep(0.05)

    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "error"
    assert isinstance(payload, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_response_pusher_blocks_instead_of_dropping_slow_consumer() -> None:
    """Chunk delivery must wait for queue space instead of dropping after 0.5s."""
    loop = asyncio.get_running_loop()
    out: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=1)
    pusher = ResponsePusher(loop, out)

    pusher.push_from_worker("chunk", ((), "messages", "first"))
    await asyncio.sleep(0.05)
    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "chunk"
    assert payload == ((), "messages", "first")

    pusher.push_from_worker("chunk", ((), "messages", "second"))
    await asyncio.sleep(0.05)
    pusher.push_from_worker("chunk", ((), "messages", "third"))
    await asyncio.sleep(0.05)

    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "chunk"
    assert payload == ((), "messages", "second")

    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "chunk"
    assert payload == ((), "messages", "third")


def test_chunk_is_goal_completion_detects_phase_tag() -> None:
    from soothe_daemon.runner.response_bridge import _chunk_is_goal_completion

    gc_chunk = (
        (),
        "messages",
        ({"type": "AIMessageChunk", "content": "report", "phase": "goal_completion"}, {}),
    )
    plain_chunk = ((), "messages", ({"type": "AIMessageChunk", "content": "hi"}, {}))
    assert _chunk_is_goal_completion(gc_chunk)
    assert not _chunk_is_goal_completion(plain_chunk)


@pytest.mark.asyncio
async def test_response_pusher_done_message() -> None:
    loop = asyncio.get_running_loop()
    out: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    pusher = ResponsePusher(loop, out)

    pusher.push_from_worker("done")
    await asyncio.sleep(0.05)

    msg_type, payload = await out.get()
    assert msg_type == "done"
    assert payload is None


@pytest.mark.asyncio
async def test_response_pusher_done_waits_when_queue_full() -> None:
    """Terminal ``done`` must not be dropped when the asyncio queue is full."""
    loop = asyncio.get_running_loop()
    out: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=1)
    pusher = ResponsePusher(loop, out)

    out.put_nowait(("chunk", ((), "messages", "blocking")))
    pusher.push_from_worker("done")

    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "chunk"
    assert payload == ((), "messages", "blocking")

    msg_type, payload = await asyncio.wait_for(out.get(), timeout=1.0)
    assert msg_type == "done"
    assert payload is None
