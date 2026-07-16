"""Tests for headless daemon cancel-on-SIGINT behaviour."""

from __future__ import annotations

import asyncio
import signal
from types import SimpleNamespace
from typing import Any

import pytest

from soothe_cli.cli.execution import daemon as daemon_exec


class _CancelRecordingClient:
    """WebSocket client stub that records whether /cancel was sent."""

    def __init__(self) -> None:
        self.cancel_commands: list[str] = []
        self._events: list[dict[str, Any] | None] = []

    def add_events(self, events: list[dict[str, Any] | None]) -> None:
        self._events.extend(events)

    async def send_input(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Protocol-1 notify — records slash_command notifications."""
        if method == "slash_command" and params:
            self.cancel_commands.append(params.get("cmd", ""))

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            # Block indefinitely so the test can trigger the signal handler.
            await asyncio.sleep(10)
            return None
        return self._events.pop(0)

    async def close(self) -> None:
        return None


class _StubSession:
    """DaemonSession stub wrapping a recording client."""

    def __init__(self, client: _CancelRecordingClient, loop_id: str) -> None:
        self._client = client
        self._loop_id = loop_id

    @property
    def client(self) -> _CancelRecordingClient:
        return self._client

    @property
    def loop_id(self) -> str:
        return self._loop_id

    async def connect(self, *, resume_loop_id: str | None = None) -> dict[str, Any]:
        del resume_loop_id
        return {"type": "session_ready", "loop_id": self._loop_id, "success": True}

    async def send_turn(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def cancel_remote_query(self) -> None:
        await self._client.notify("slash_command", {"cmd": "/cancel"})

    async def close(self, **_kwargs: Any) -> None:
        await self._client.close()


class _RecorderProcessor:
    """EventProcessor stub that records processed frames."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.events: list[dict[str, Any]] = []

    def process_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _patch_daemon_deps(
    monkeypatch: pytest.MonkeyPatch,
    stub_client: _CancelRecordingClient,
    active_loop_id: str,
) -> None:
    """Apply common monkeypatches for daemon test setup."""

    def _session_factory(*_args: Any, **_kwargs: Any) -> _StubSession:
        return _StubSession(stub_client, active_loop_id)

    monkeypatch.setattr(daemon_exec, "EventProcessor", _RecorderProcessor)
    monkeypatch.setattr(daemon_exec, "websocket_url_from_config", lambda _cfg: "ws://unit.test")
    monkeypatch.setattr(daemon_exec, "DaemonSession", _session_factory)


@pytest.mark.asyncio
async def test_send_cancel_to_daemon_sends_command() -> None:
    """_send_cancel_to_daemon should send /cancel via the session."""
    stub_client = _CancelRecordingClient()
    session = _StubSession(stub_client, "loop-1")
    await daemon_exec._send_cancel_to_daemon(session)
    assert "/cancel" in stub_client.cancel_commands


@pytest.mark.asyncio
async def test_send_cancel_to_daemon_is_tolerant_of_errors() -> None:
    """_send_cancel_to_daemon should not raise even if notify fails."""
    stub_client = _CancelRecordingClient()
    session = _StubSession(stub_client, "loop-1")

    async def _failing_cancel() -> None:
        raise ConnectionError("boom")

    session.cancel_remote_query = _failing_cancel  # type: ignore[method-assign]
    # Should not raise.
    await daemon_exec._send_cancel_to_daemon(session)
    assert stub_client.cancel_commands == []


@pytest.mark.asyncio
async def test_sigint_flag_triggers_cancel_then_task_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the SIGINT flag is set, the loop should send /cancel then cancel the task."""
    active_loop_id = "loop-sigint-flag-test"
    stub_client = _CancelRecordingClient()
    # Only provide the "running" event — read_event will block after that,
    # giving the test time to invoke the signal handler.
    stub_client.add_events(
        [
            {"type": "status", "state": "running", "loop_id": active_loop_id},
        ]
    )

    _patch_daemon_deps(monkeypatch, stub_client, active_loop_id)

    # Capture the SIGINT handler callback installed by _run_headless_session_once.
    captured_handler: Any = None
    original_add_signal_handler = asyncio.get_running_loop().add_signal_handler

    def _capturing_add_handler(sig: int, callback: Any, *args: Any) -> None:
        nonlocal captured_handler
        if sig == signal.SIGINT:
            captured_handler = callback
        # Don't install on the real loop to avoid interfering with pytest.

    loop = asyncio.get_running_loop()
    loop.add_signal_handler = _capturing_add_handler  # type: ignore[assignment]

    cfg = SimpleNamespace()
    task = asyncio.create_task(
        daemon_exec._run_headless_session_once(
            cfg, prompt="test", resume_loop_id=None, autonomous=False, max_iterations=None
        )
    )

    # Give the session time to start and install the signal handler.
    await asyncio.sleep(0.1)

    # Invoke the captured SIGINT handler (simulates Ctrl+C).
    assert captured_handler is not None, "SIGINT handler should have been installed"
    captured_handler()

    # Wait briefly for the cancel to be sent.
    for _ in range(20):
        if stub_client.cancel_commands:
            break
        await asyncio.sleep(0.05)

    # Cancel the task to clean up.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Restore the original add_signal_handler.
    loop.add_signal_handler = original_add_signal_handler  # type: ignore[assignment]

    # The daemon should have received /cancel.
    assert "/cancel" in stub_client.cancel_commands


@pytest.mark.asyncio
async def test_cancelled_error_sends_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """asyncio.CancelledError during headless session should attempt /cancel."""
    active_loop_id = "loop-cancel-err-test"
    stub_client = _CancelRecordingClient()

    _patch_daemon_deps(monkeypatch, stub_client, active_loop_id)

    # Make read_event raise CancelledError to simulate task cancellation.
    async def _read_event_raises_cancelled() -> dict[str, Any] | None:
        raise asyncio.CancelledError

    stub_client.read_event = _read_event_raises_cancelled  # type: ignore[method-assign]

    cfg = SimpleNamespace()
    with pytest.raises(asyncio.CancelledError):
        await daemon_exec._run_headless_session_once(
            cfg, prompt="test", resume_loop_id=None, autonomous=False, max_iterations=None
        )

    assert "/cancel" in stub_client.cancel_commands
