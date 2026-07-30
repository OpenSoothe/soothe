"""Tests for cooperative vs unexpected stream cancel policy."""

from __future__ import annotations

import asyncio
import threading

import pytest

from soothe_daemon.runner.stream_cancel import (
    await_cancellable_stream,
    emit_terminal_for_cancelled_error,
)


@pytest.mark.asyncio
async def test_await_cancellable_stream_completes_normally() -> None:
    """Happy path: stream finishes without cancel."""
    calls = {"n": 0}

    async def _stream() -> None:
        calls["n"] += 1

    cancel_event = threading.Event()
    await await_cancellable_stream(
        _stream,
        cancel_event=cancel_event,
        worker_id="w0",
        loop_id="loop",
        request_id="req",
        poll_interval_s=0.05,
    )
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_await_cancellable_stream_retries_unexpected_cancel() -> None:
    """Internal CancelledError without cancel_event retries then succeeds."""
    calls = {"n": 0}

    async def _stream() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError

    cancel_event = threading.Event()
    await await_cancellable_stream(
        _stream,
        cancel_event=cancel_event,
        worker_id="w0",
        loop_id="loop",
        request_id="req",
        unexpected_retries=1,
        poll_interval_s=0.05,
    )
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_await_cancellable_stream_unexpected_exhausted_raises_runtime_error() -> None:
    """Exhausted unexpected cancels become RuntimeError (not CancelledError)."""

    async def _stream() -> None:
        raise asyncio.CancelledError

    cancel_event = threading.Event()
    with pytest.raises(RuntimeError, match="not user-cancelled"):
        await await_cancellable_stream(
            _stream,
            cancel_event=cancel_event,
            worker_id="w0",
            loop_id="loop",
            request_id="req",
            unexpected_retries=1,
            poll_interval_s=0.05,
        )


@pytest.mark.asyncio
async def test_await_cancellable_stream_cooperative_cancel_raises_cancelled() -> None:
    """cancel_event + task cancel surfaces as CancelledError (user cancel)."""
    cancel_event = threading.Event()

    async def _stream() -> None:
        cancel_event.set()
        await asyncio.sleep(60)

    with pytest.raises(asyncio.CancelledError):
        await await_cancellable_stream(
            _stream,
            cancel_event=cancel_event,
            worker_id="w0",
            loop_id="loop",
            request_id="req",
            poll_interval_s=0.05,
        )


def test_emit_terminal_cooperative_emits_cancelled() -> None:
    """cancel_event set → cancelled terminal."""
    cancel_event = threading.Event()
    cancel_event.set()
    seen: list[str] = []

    emit_terminal_for_cancelled_error(
        cancel_event=cancel_event,
        emit_cancelled=lambda: seen.append("cancelled"),
        emit_error=lambda _exc: seen.append("error"),
        worker_id="w0",
        loop_id="loop",
        request_id="req",
        where="test",
    )
    assert seen == ["cancelled"]


def test_emit_terminal_unexpected_emits_error() -> None:
    """cancel_event clear → error terminal (loop not interrupted as cancel)."""
    cancel_event = threading.Event()
    seen: list[object] = []

    emit_terminal_for_cancelled_error(
        cancel_event=cancel_event,
        emit_cancelled=lambda: seen.append("cancelled"),
        emit_error=lambda exc: seen.append(exc),
        worker_id="w0",
        loop_id="loop",
        request_id="req",
        where="test",
    )
    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)
    assert "not user-cancelled" in str(seen[0])
