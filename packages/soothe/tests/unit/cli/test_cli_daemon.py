"""Tests for daemon autonomous propagation and client payloads."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon, WebSocketClient
from soothe.daemon.server import _ClientConn
from soothe_cli.cli.execution import daemon as daemon_exec, headless as headless_exec
from soothe_cli.tui import daemon_session as ux_client_session


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
        self.touched_thread_ids: list[str] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.lifecycle.thread.started"})

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        self.touched_thread_ids.append(thread_id)


class _FakeRunnerWithMessages:
    """Runner stub that yields AI messages for session logging tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-test"
        self.calls: list[dict] = []
        self.touched_thread_ids: list[str] = []

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

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        self.touched_thread_ids.append(thread_id)


class _FakeRunnerThatSwapsThread:
    """Runner stub that changes current_thread_id mid-query."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-start"
        self.calls: list[dict] = []
        self.touched_thread_ids: list[str] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.plan.created", "goal": text, "steps": []})
        self.current_thread_id = "thread-final"

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        self.touched_thread_ids.append(thread_id)


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
    daemon._query_running = False

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
async def test_cancel_command_bypasses_input_queue() -> None:
    """IG-161: /cancel must not enqueue — input loop may be blocked on run_query."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    cancel_mock = AsyncMock()
    daemon._query_engine = SimpleNamespace(cancel_current_query=cancel_mock)  # type: ignore[attr-defined]

    await daemon._handle_client_message("client-1", {"type": "command", "cmd": "/cancel "})

    cancel_mock.assert_awaited_once()
    assert daemon._current_input_queue.qsize() == 0


@pytest.mark.asyncio
async def test_exit_and_quit_commands_bypass_input_queue() -> None:
    """IG-161: /exit and /quit must not enqueue — input loop may be blocked on run_query."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    await daemon._handle_client_message("client-1", {"type": "command", "cmd": " /exit "})
    assert daemon._current_input_queue.qsize() == 0
    assert sent == [{"type": "status", "state": "detached"}]

    sent.clear()
    await daemon._handle_client_message("client-1", {"type": "command", "cmd": "/QUIT"})
    assert daemon._current_input_queue.qsize() == 0
    assert sent == [{"type": "status", "state": "detached"}]


@pytest.mark.asyncio
async def test_non_cancel_command_still_enqueues() -> None:
    """Commands not handled in MessageRouter continue to use the sequential input queue."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._query_engine = SimpleNamespace(cancel_current_query=AsyncMock())  # type: ignore[attr-defined]

    await daemon._handle_client_message("client-1", {"type": "command", "cmd": "/help"})

    queued = await daemon._current_input_queue.get()
    assert queued["type"] == "command"
    assert queued["cmd"] == "/help"


@pytest.mark.asyncio
async def test_daemon_input_message_returns_busy_error_while_query_running() -> None:
    daemon = SootheDaemon(SootheConfig())
    daemon._query_running = True
    daemon._runner = SimpleNamespace(current_thread_id="thread-busy")

    transport = SimpleNamespace(send=AsyncMock())
    transport_client = SimpleNamespace()  # Mock transport client
    session = SimpleNamespace(transport=transport, transport_client=transport_client)
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=session))  # type: ignore[attr-defined]

    await daemon._handle_client_message(
        "client-1",
        {"type": "input", "text": "crawl", "autonomous": True, "max_iterations": 12},
    )

    transport.send.assert_awaited_once_with(
        transport_client,
        {
            "type": "error",
            "code": "DAEMON_BUSY",
            "message": (
                "Daemon is already processing another query. "
                "Wait for it to finish or cancel it before starting a new one."
            ),
            "thread_id": "thread-busy",
        },
    )


@pytest.mark.asyncio
async def test_websocket_client_send_input_includes_options() -> None:
    client = WebSocketClient()
    captured: list[dict] = []

    async def _fake_send(payload: dict) -> None:
        captured.append(payload)

    client._connected = True
    client.send = _fake_send  # type: ignore[method-assign]
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
    from soothe.logging import ThreadLogger

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
    - Only explicit 'soothe-daemon stop' should shutdown daemon
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

    await ux_client_session.connect_websocket_with_retries(_RetryClient())

    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_connect_with_retries_raises_after_exhaustion(monkeypatch) -> None:
    class _FailingClient:
        async def connect(self) -> None:
            raise FileNotFoundError("missing socket")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(ux_client_session, "_CONNECT_RETRY_COUNT", 2)

    with pytest.raises(FileNotFoundError):
        await ux_client_session.connect_websocket_with_retries(_FailingClient())


@pytest.mark.asyncio
async def test_websocket_client_wait_for_daemon_ready_returns_ready_event() -> None:
    seq = _SequencedClient(
        events=[
            {"type": "status", "state": "idle", "thread_id": ""},
            {"type": "daemon_ready", "state": "ready"},
        ]
    )
    client = WebSocketClient()
    client._connected = True
    client.read_event = seq.read_event  # type: ignore[method-assign]

    event = await client.wait_for_daemon_ready(ready_timeout_s=0.5)

    assert event == {"type": "daemon_ready", "state": "ready"}


@pytest.mark.asyncio
async def test_websocket_client_wait_for_daemon_ready_raises_on_error_state() -> None:
    seq = _SequencedClient(events=[{"type": "daemon_ready", "state": "error", "message": "startup failed"}])
    client = WebSocketClient()
    client._connected = True
    client.read_event = seq.read_event  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="startup failed"):
        await client.wait_for_daemon_ready(ready_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_thread_status_skips_empty_handshake_status() -> None:
    client = _SequencedClient(
        events=[
            {"type": "status", "state": "idle", "thread_id": ""},
            {"type": "status", "state": "idle", "thread_id": "thread-123", "new_thread": True},
        ]
    )

    event = await ux_client_session._wait_for_thread_status(client, timeout_s=0.5)

    assert event["thread_id"] == "thread-123"


@pytest.mark.asyncio
async def test_daemon_initial_status_no_thread_leak() -> None:
    """Test that daemon initial status doesn't leak cached thread_id to new clients."""
    daemon = SootheDaemon(SootheConfig())
    # Set up a runner with an existing thread_id (simulating previous session)
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._runner.current_thread_id = "old-thread-123"  # type: ignore[attr-defined]
    daemon._running = True

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
    from soothe_sdk.protocol import decode

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


@pytest.mark.asyncio
async def test_run_headless_via_daemon_returns_direct_error_before_query_start(monkeypatch) -> None:
    events = iter(
        [
            {"type": "status", "state": "idle", "thread_id": ""},
            {"type": "daemon_ready", "state": "ready"},
            {"type": "status", "state": "idle", "thread_id": "thread-123", "new_thread": True},
            {"type": "subscription_confirmed", "thread_id": "thread-123", "client_id": "c1", "verbosity": "normal"},
            {"type": "error", "code": "DAEMON_BUSY", "message": "busy"},
        ]
    )

    class _BusyClient:
        async def connect(self) -> None:
            return None

        async def request_daemon_ready(self) -> None:
            return None

        async def wait_for_daemon_ready(self, ready_timeout_s: float = 10.0) -> dict[str, Any]:
            return {"type": "daemon_ready", "state": "ready"}

        async def send_new_thread(self, workspace: str | None = None) -> None:
            return None

        async def send_resume_thread(self, thread_id: str, workspace: str | None = None) -> None:
            return None

        async def subscribe_thread(self, thread_id: str, verbosity: str = "normal") -> None:
            return None

        async def wait_for_subscription_confirmed(
            self, thread_id: str, verbosity: str = "normal", timeout: float = 5.0
        ) -> None:
            return None

        async def send_input(
            self,
            text: str,
            autonomous: bool = False,  # noqa: FBT001, FBT002
            max_iterations: int | None = None,
            subagent: str | None = None,
        ) -> None:
            return None

        async def read_event(self) -> dict[str, Any] | None:
            return next(events, None)

        async def close(self) -> None:
            return None

    stderr: list[str] = []

    monkeypatch.setattr("soothe.daemon.websocket_client.WebSocketClient", lambda url=None: _BusyClient())
    monkeypatch.setattr(typer, "echo", lambda msg, err=False: stderr.append(str(msg)) if err else None)

    code = await daemon_exec.run_headless_via_daemon(SootheConfig(), "analyze project structure")

    assert code == 1
    assert stderr == ["Daemon error: busy"]


def test_run_headless_stops_stale_daemon_before_restart(monkeypatch) -> None:
    cfg = SootheConfig()
    stop_running = MagicMock()
    daemon_start = MagicMock()
    captured: dict[str, object] = {}

    monkeypatch.setattr(headless_exec.SootheDaemon, "_is_port_live", staticmethod(lambda h, p: False))
    monkeypatch.setattr(headless_exec.SootheDaemon, "is_running", staticmethod(lambda: True))
    monkeypatch.setattr(headless_exec.SootheDaemon, "stop_running", staticmethod(stop_running))
    monkeypatch.setattr("soothe.ux.cli.commands.daemon_cmd.daemon_start", daemon_start)

    def _fake_asyncio_run(coro: object) -> int:
        captured["coro"] = coro
        return 0

    monkeypatch.setattr("asyncio.run", _fake_asyncio_run)
    monkeypatch.setattr(headless_exec.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit) as exc:
        headless_exec.run_headless(cfg, "analyze project structure")

    assert exc.value.code == 0
    stop_running.assert_called_once()
    daemon_start.assert_called_once()
    assert captured["coro"].cr_code.co_name == "run_headless_via_daemon"
    captured["coro"].close()


@pytest.mark.asyncio
async def test_daemon_ready_request_replies_without_session() -> None:
    daemon = SootheDaemon(SootheConfig())
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=None))  # type: ignore[attr-defined]

    sent: list[dict[str, Any]] = []

    async def _fake_send(client: Any, msg: dict[str, Any]) -> None:
        assert isinstance(client, _ClientConn)
        sent.append(msg)

    daemon._send = _fake_send  # type: ignore[method-assign]
    daemon._readiness_state = "ready"
    daemon._readiness_message = None

    client = _ClientConn(reader=SimpleNamespace(), writer=SimpleNamespace())
    await daemon._handle_client_message(client, {"type": "daemon_ready"})

    assert sent == [{"type": "daemon_ready", "state": "ready", "message": None}]


@pytest.mark.asyncio
async def test_detach_ignores_connection_loss_for_transport_session() -> None:
    daemon = SootheDaemon(SootheConfig())
    transport = SimpleNamespace(send=AsyncMock(side_effect=ConnectionError("Connection lost")))
    transport_client = SimpleNamespace()  # Mock transport client
    session = SimpleNamespace(transport=transport, transport_client=transport_client)
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=session))  # type: ignore[attr-defined]

    await daemon._handle_client_message("client-1", {"type": "detach"})

    transport.send.assert_awaited_once()
