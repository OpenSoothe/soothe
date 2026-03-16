"""Tests for daemon autonomous propagation and client payloads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.cli.daemon import DaemonClient, SootheDaemon, _ClientConn
from soothe.config import SootheConfig


class _FakeRunner:
    """Minimal runner stub for daemon query tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-1"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.session.started"})


@pytest.mark.asyncio
async def test_daemon_run_query_passes_autonomous_kwargs() -> None:
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]
    await daemon._run_query("download skills", autonomous=True, max_iterations=42)

    assert daemon._runner.calls  # type: ignore[attr-defined]
    call = daemon._runner.calls[0]  # type: ignore[attr-defined]
    assert call["text"] == "download skills"
    assert call["thread_id"] == "thread-1"
    assert call["autonomous"] is True
    assert call["max_iterations"] == 42
    assert any(msg.get("type") == "event" for msg in sent)


@pytest.mark.asyncio
async def test_daemon_input_message_enqueues_options() -> None:
    daemon = SootheDaemon(SootheConfig())
    client = _ClientConn(reader=SimpleNamespace(), writer=SimpleNamespace())

    await daemon._handle_client_message(
        client,
        {"type": "input", "text": "crawl", "autonomous": True, "max_iterations": 12},
    )

    queued = await daemon._current_input_queue.get()
    assert queued["type"] == "input"
    assert queued["text"] == "crawl"
    assert queued["autonomous"] is True
    assert queued["max_iterations"] == 12


@pytest.mark.asyncio
async def test_daemon_client_send_input_includes_options() -> None:
    client = DaemonClient()
    captured: list[dict] = []

    async def _fake_send(payload: dict) -> None:
        captured.append(payload)

    client._send = _fake_send  # type: ignore[method-assign]
    await client.send_input("run task", autonomous=True, max_iterations=9)

    assert captured == [
        {
            "type": "input",
            "text": "run task",
            "autonomous": True,
            "max_iterations": 9,
        }
    ]
