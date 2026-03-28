"""Tests for daemon autonomous propagation and client payloads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.daemon import DaemonClient, SootheDaemon
from soothe.daemon.server import _ClientConn
from soothe.ux.cli.execution import daemon as daemon_exec, headless as headless_exec


class _SequencedClient:
    def __init__(self, events: list[dict[str, Any] | None]) -> None:
        self._events = list(events)

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            return None
        return self._events.pop(0)


class _FakeRunner:
    """Minimal runner stub for daemon query tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-1"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.lifecycle.thread.started"})


class _FakeRunnerWithMessages:
    """Runner stub that yields AI messages for session logging tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-test"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        from langchain_core.messages import AIMessage

        self.calls.append({"text": text, **kwargs})

        # Yield a custom event
        yield ((), "custom", {"type": "soothe.lifecycle.thread.started"})

        # Yield a user message marker (not logged)
        yield ((), "custom", {"type": "user.input", "text": text})

        # Yield an AI message with text content
        ai_msg = AIMessage(content="Hello from assistant", id="msg-1")
        yield ((), "messages", (ai_msg, {}))


class _FakeRunnerThatSwapsThread:
    """Runner stub that changes current_thread_id mid-query."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-start"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.plan.created", "goal": text, "steps": []})
        self.current_thread_id = "thread-final"


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


@pytest.mark.asyncio
async def test_daemon_logs_thread_to_file(tmp_path: Any) -> None:
    """Test that daemon logs user input and assistant responses to thread file."""
    from soothe.daemon.thread_logger import ThreadLogger

    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunnerWithMessages()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Create a thread logger with temp directory
    thread_logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="thread-test")
    daemon._thread_logger = thread_logger

    # Run a query
    await daemon._run_query("Hello, assistant")

    # Verify thread was logged
    records = thread_logger.read_recent_records(limit=20)

    # Should have: user input, custom event, assistant response
    user_inputs = [r for r in records if r.get("kind") == "conversation" and r.get("role") == "user"]
    assistant_responses = [r for r in records if r.get("kind") == "conversation" and r.get("role") == "assistant"]
    events = [r for r in records if r.get("kind") == "event"]

    assert len(user_inputs) == 1
    assert user_inputs[0].get("text") == "Hello, assistant"

    assert len(assistant_responses) == 1
    assert "Hello from assistant" in assistant_responses[0].get("text", "")

    assert len(events) >= 1  # At least the thread.started event


@pytest.mark.asyncio
async def test_daemon_handles_slash_commands() -> None:
    """Test that daemon executes slash commands and sends responses."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Test /help command
    await daemon._handle_command("/help")

    # Should have sent a command_response message
    response_msgs = [msg for msg in sent if msg.get("type") == "command_response"]
    assert len(response_msgs) >= 1

    # The response should contain command table
    content = response_msgs[0].get("content", "")
    assert "/help" in content
    assert "/exit" in content
    assert "/memory" in content


@pytest.mark.asyncio
async def test_daemon_command_exit_does_not_stop_daemon() -> None:
    """Test that /exit and /quit commands do NOT stop the daemon (IG-085, RFC-0013).

    Per RFC-0013 daemon lifecycle semantics:
    - /exit and /quit should detach client, not stop daemon
    - Only explicit 'soothe daemon stop' should shutdown daemon
    """
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Test /exit command
    await daemon._handle_command("/exit")

    # IG-085: Daemon should KEEP RUNNING (not stop)
    assert daemon._running is True


@pytest.mark.asyncio
async def test_connect_with_retries_succeeds_after_transient_refusal(monkeypatch) -> None:
    attempts = {"count": 0}

    class _RetryClient:
        async def connect(self) -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionRefusedError("not ready")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    await daemon_exec._connect_with_retries(_RetryClient())

    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_connect_with_retries_raises_after_exhaustion(monkeypatch) -> None:
    class _FailingClient:
        async def connect(self) -> None:
            raise FileNotFoundError("missing socket")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(daemon_exec, "_CONNECT_RETRY_COUNT", 2)

    with pytest.raises(FileNotFoundError):
        await daemon_exec._connect_with_retries(_FailingClient())


def test_wait_for_daemon_ready_uses_configured_socket(monkeypatch, tmp_path: Path) -> None:
    cfg = SootheConfig(daemon={"transports": {"unix_socket": {"path": str(tmp_path / "custom.sock")}}})
    observed: list[Path] = []

    monkeypatch.setattr(headless_exec.time, "sleep", lambda _delay: None)

    def _fake_is_socket_ready(sock: Path) -> bool:
        observed.append(sock)
        return True

    monkeypatch.setattr(headless_exec, "_is_socket_ready", _fake_is_socket_ready)

    assert headless_exec._wait_for_daemon_ready(cfg, timeout_s=0.5) is True
    assert observed == [tmp_path / "custom.sock"]


@pytest.mark.asyncio
async def test_wait_for_thread_status_skips_empty_handshake_status() -> None:
    client = _SequencedClient(
        events=[
            {"type": "status", "state": "idle", "thread_id": ""},
            {"type": "status", "state": "idle", "thread_id": "thread-123", "new_thread": True},
        ]
    )

    event = await daemon_exec._wait_for_thread_status(client, timeout_s=0.5)

    assert event["thread_id"] == "thread-123"


@pytest.mark.asyncio
async def test_daemon_initial_status_no_thread_leak() -> None:
    """Test that daemon initial status doesn't leak cached thread_id to new clients."""
    from asyncio import StreamWriter

    from soothe.daemon.thread_logger import InputHistory

    daemon = SootheDaemon(SootheConfig())
    # Set up a runner with an existing thread_id (simulating previous session)
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._runner.current_thread_id = "old-thread-123"  # type: ignore[attr-defined]
    daemon._running = True
    daemon._input_history = InputHistory()  # Initialize input history

    sent_messages: list[bytes] = []

    # Mock reader
    class MockReader:
        async def readline(self) -> bytes:
            return b""  # EOF immediately

    # Create a mock StreamWriter that captures writes
    reader = MockReader()

    # Use asyncio.StreamWriter mock - we need to mock it properly
    class MockStreamWriter:
        def write(self, data: bytes) -> None:
            sent_messages.append(data)

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    writer = MockStreamWriter()

    # Handle client connection
    await daemon._handle_client(reader, writer)  # type: ignore[arg-type]

    # Decode the initial status message
    from soothe.daemon.protocol import decode

    assert len(sent_messages) > 0, "Should have sent initial status message"
    initial_msg = decode(sent_messages[0])
    assert initial_msg is not None
    assert initial_msg["type"] == "status"
    # Critical: thread_id should be empty, not "old-thread-123"
    assert initial_msg["thread_id"] == "", "Initial status should not leak cached thread_id"
    assert initial_msg["state"] in ("running", "idle", "stopped")


@pytest.mark.asyncio
async def test_daemon_run_query_broadcasts_idle_to_original_thread() -> None:
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunnerThatSwapsThread()  # type: ignore[attr-defined]

    sent: list[dict[str, Any]] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]
    await daemon._run_query("analyze project structure")

    status_messages = [msg for msg in sent if msg.get("type") == "status"]
    assert status_messages[0]["state"] == "running"
    assert status_messages[0]["thread_id"] == "thread-start"
    assert status_messages[-1]["state"] == "idle"
    assert status_messages[-1]["thread_id"] == "thread-start"
