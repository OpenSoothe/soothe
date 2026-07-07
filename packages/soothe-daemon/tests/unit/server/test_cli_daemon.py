"""Tests for daemon autonomous propagation and client payloads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer
from soothe.config import SootheConfig
from soothe_cli.cli.execution import daemon as daemon_exec
from soothe_cli.cli.execution import headless as headless_exec
from soothe_sdk.client import session as sdk_session  # For retry logic (moved from CLI)

from soothe_daemon import SootheDaemon, WebSocketClient
from soothe_daemon.protocol import MessageRouter


def _mark_handshake(daemon: SootheDaemon, client_id: str = "client-1") -> None:
    """Mark protocol-1 handshake complete for unit tests."""
    daemon._message_router._handshake_state[client_id] = ("1", [])


async def _await_background_query_idle(
    daemon: SootheDaemon,
    sent: list[dict[str, Any]],
    *,
    timeout_s: float = 2.0,
) -> list[dict[str, Any]]:
    """Wait for IG-054 background query task to broadcast running and idle status.

    The query task may finish and unregister from ``_active_threads`` before the
    test observes it, so poll ``sent`` until both status transitions appear.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        for task in list(getattr(daemon, "_active_threads", {}).values()):
            if task and not task.done():
                await task
        status = [m for m in sent if m.get("type") == "status"]
        if any(m.get("state") == "running" for m in status) and any(
            m.get("state") == "idle" for m in status
        ):
            return status
        await asyncio.sleep(0.01)
    status = [m for m in sent if m.get("type") == "status"]
    states = [m.get("state") for m in status]
    msg = f"Timed out waiting for running+idle status broadcasts; got {states!r}"
    raise AssertionError(msg)


class _SequencedClient:
    def __init__(self, events: list[dict[str, Any] | None]) -> None:
        self._events = list(events)

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            return None
        return self._events.pop(0)

    async def _read_inbound_event(self) -> dict[str, Any] | None:
        # Same behavior as read_event for test mocks
        return await self.read_event()

    def is_connection_alive(self) -> bool:
        return True


class _FakeRunner:
    """Minimal runner stub for daemon query tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-1"
        self.calls: list[dict] = []
        self.touched_thread_ids: list[str] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.internal.iteration.started"})

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        self.touched_thread_ids.append(thread_id)

    async def memory_stats(self) -> dict[str, Any]:
        """Stub for memory_stats RPC command (RFC-454)."""
        return {"backend": "test", "entries": 5}


class _FakeLoopRunner:
    """Minimal loop runner stub that delegates to a fake runner."""

    def __init__(
        self, runner: _FakeRunner | _FakeRunnerWithMessages | _FakeRunnerThatSwapsThread
    ) -> None:
        self._runner = runner

    async def run(self, request: Any) -> Any:  # type: ignore[no-untyped-def]  # noqa: ANN401
        async for chunk in self._runner.astream(
            request.user_input,
            thread_id=request.thread_id,
            workspace=request.resolve_workspace_path(),
            autonomous=request.autonomous,
            max_iterations=request.max_iterations,
            preferred_subagent=request.preferred_subagent,
        ):
            yield chunk

    async def cancel(self) -> None:
        pass


class _FakeRunnerFactory:
    """Creates ``_FakeLoopRunner`` instances backed by a shared runner."""

    def __init__(
        self, runner: _FakeRunner | _FakeRunnerWithMessages | _FakeRunnerThatSwapsThread
    ) -> None:
        self._runner = runner

    def create_runner(self, loop_id: str) -> _FakeLoopRunner:  # noqa: ARG002
        return _FakeLoopRunner(self._runner)


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
        yield ((), "custom", {"type": "soothe.internal.iteration.started"})

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
        yield ((), "custom", {"type": "soothe.cognition.plan.created", "goal": text, "steps": []})
        self.current_thread_id = "thread-final"

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        self.touched_thread_ids.append(thread_id)


class _FakeThreadRegistry:
    """Minimal thread registry stub for daemon query tests."""

    def get(self, _thread_id: str) -> None:
        return None

    def get_thread_loop(self, _thread_id: str) -> str:
        return ""

    def get_workspace(self, _thread_id: str) -> Path:
        return Path.cwd()

    def ensure(self, _thread_id: str, *, is_draft: bool = False) -> None:
        del is_draft

    def set_workspace(self, _thread_id: str, _workspace: Path) -> None:
        return None


@pytest.mark.asyncio
async def test_daemon_run_query_passes_autonomous_kwargs() -> None:
    daemon = SootheDaemon(SootheConfig())
    fake_runner = _FakeRunner()
    daemon._runner = fake_runner  # type: ignore[attr-defined]
    daemon._runner_factory = _FakeRunnerFactory(fake_runner)  # type: ignore[attr-defined]
    daemon._session_manager = SimpleNamespace(  # type: ignore[attr-defined]
        claim_loop_ownership=lambda *_args, **_kwargs: None,
        release_loop_ownership=lambda *_args, **_kwargs: None,
        subscribe_loop=lambda *_args, **_kwargs: True,
        get_stream_delivery=lambda *_args, **_kwargs: "batch",
        await_loop_delivery_drained=AsyncMock(return_value=True),
        get_clients_for_loop=AsyncMock(return_value=[]),  # RFC-450 §9.4
        get_loop_subscription_id=AsyncMock(return_value=None),  # RFC-450 §9.4
    )
    daemon._message_router = SimpleNamespace(  # type: ignore[attr-defined]
        _send_complete=lambda *_args, **_kwargs: None,  # RFC-450 §9.4
    )
    daemon._query_state_lock = asyncio.Lock()  # type: ignore[attr-defined]
    daemon._persistence_manager = SimpleNamespace(get_loop_metadata=AsyncMock(return_value=None))  # type: ignore[attr-defined]
    daemon._thread_registry = _FakeThreadRegistry()  # type: ignore[attr-defined]
    daemon._active_stream_loop_ids = set()  # type: ignore[attr-defined]
    daemon._config = SimpleNamespace(
        observability=SimpleNamespace(
            thread_logging_retention_days=7, thread_logging_max_size_mb=10
        ),
        agent=SimpleNamespace(
            loop=SimpleNamespace(
                output_streaming=SimpleNamespace(
                    adaptive_threshold_chars=500,
                    adaptive_block_chars=1024,
                    adaptive_block_interval_ms=250,
                    file_output_threshold_chars=0,
                    file_output_preview_chars=500,
                    file_output_dir=None,
                    streaming_interval_ms=300,
                    message_coalesce_enabled=True,
                    tool_batch_enabled=True,
                    tool_batch_interval_ms=200,
                    suppress_redundant_stream_tool_updates=True,
                    skip_redundant_tool_message_wire=False,
                )
            )
        ),
    )  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]
    await daemon._query_engine.run_query(
        "download skills", loop_id="loop-u", autonomous=True, max_iterations=42
    )

    await _await_background_query_idle(daemon, sent)

    assert daemon._runner.calls  # type: ignore[attr-defined]
    call = daemon._runner.calls[0]  # type: ignore[attr-defined]
    assert call["text"] == "download skills"
    assert call["thread_id"] == "thread-1"
    assert call["autonomous"] is True
    assert call["max_iterations"] == 42


@pytest.mark.asyncio
async def test_loop_input_enqueues_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """``loop_input`` is normalized and placed on the per-loop dispatcher queue."""

    async def _stub_ensure(_self: MessageRouter, _loop_id: str) -> bool:
        return True

    monkeypatch.setattr(MessageRouter, "_ensure_loop_exists", _stub_ensure)

    daemon = SootheDaemon(SootheConfig())
    loop_id = "loop-9"
    session = SimpleNamespace(subscriptions={loop_id})
    enqueue = AsyncMock()
    daemon._loop_input_dispatcher = SimpleNamespace(enqueue=enqueue)
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=session))  # type: ignore[attr-defined]
    _mark_handshake(daemon)

    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "crawl",
                "autonomous": True,
                "max_iterations": 12,
            },
            "id": "r-loop-input-1",
        },
    )

    enqueue.assert_awaited()
    body = enqueue.call_args[0][1]
    assert body["type"] == "input"
    assert body["text"] == "crawl"
    assert body["autonomous"] is True
    assert body["max_iterations"] == 12


@pytest.mark.asyncio
async def test_cancel_command_bypasses_input_queue() -> None:
    """IG-161: /cancel must not enqueue — targets ``QueryEngine.cancel_loop`` directly."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    cancel_mock = AsyncMock()
    daemon._query_engine = SimpleNamespace(cancel_loop=cancel_mock)  # type: ignore[attr-defined]
    loop_id = "loop-sub"
    session = SimpleNamespace(subscriptions={loop_id})
    daemon._session_manager = SimpleNamespace(
        get_owned_loop=AsyncMock(return_value=None),
        get_session=AsyncMock(return_value=session),
    )  # type: ignore[attr-defined]
    _mark_handshake(daemon)

    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/cancel "},
        },
    )

    cancel_mock.assert_awaited_once_with(loop_id)
    assert daemon._loop_input_dispatcher.total_queued() == 0


@pytest.mark.asyncio
async def test_exit_and_quit_commands_bypass_input_queue() -> None:
    """IG-161: /exit and /quit must not enqueue — input loop may be blocked on run_query."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]

    # IG-248: Mock _send_client_message instead of _broadcast
    sent_to_client: list[dict] = []

    async def _fake_send_client_message(cid: str, msg: dict) -> None:
        sent_to_client.append({"client_id": cid, "msg": msg})

    daemon._send_client_message = _fake_send_client_message  # type: ignore[method-assign]
    _mark_handshake(daemon)

    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": " /exit "},
        },
    )
    assert daemon._loop_input_dispatcher.total_queued() == 0
    # IG-248: Direct send to client (no thread_id, deprecated legacy socket)
    assert sent_to_client == [
        {"client_id": "client-1", "msg": {"type": "status", "state": "detached"}}
    ]

    sent_to_client.clear()
    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/QUIT"},
        },
    )
    assert daemon._loop_input_dispatcher.total_queued() == 0
    assert sent_to_client == [
        {"client_id": "client-1", "msg": {"type": "status", "state": "detached"}}
    ]


@pytest.mark.asyncio
async def test_non_cancel_command_still_enqueues() -> None:
    """Slash commands are serialized on the subscribed loop's dispatcher queue."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._query_engine = SimpleNamespace(cancel_loop=AsyncMock())  # type: ignore[attr-defined]
    loop_id = "loop-cmd"
    session = SimpleNamespace(subscriptions={loop_id})
    enqueue = AsyncMock()
    daemon._loop_input_dispatcher = SimpleNamespace(enqueue=enqueue)
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=session))  # type: ignore[attr-defined]
    _mark_handshake(daemon)

    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/help"},
        },
    )

    enqueue.assert_awaited_once()
    assert enqueue.call_args[0][0] == loop_id
    # The slash_command handler builds a fresh queue payload with type "command"
    # (not the flattened envelope method name).
    assert enqueue.call_args[0][1]["type"] == "command"
    assert enqueue.call_args[0][1]["cmd"] == "/help"


@pytest.mark.asyncio
async def test_websocket_client_send_input_includes_options() -> None:
    client = WebSocketClient()
    captured: list[dict] = []

    async def _fake_send(payload: dict) -> None:
        captured.append(payload)

    client._connected = True
    client.send = _fake_send  # type: ignore[method-assign]
    await client.send_input("loop-1", "run task", autonomous=True, max_iterations=9)

    # Under protocol-1, send_input delegates to notify("loop_input", params).
    assert len(captured) == 1
    msg = captured[0]
    assert msg["proto"] == "1"
    assert msg["type"] == "notification"
    assert msg["method"] == "loop_input"
    params = msg["params"]
    assert params["loop_id"] == "loop-1"
    assert params["content"] == "run task"
    assert params["autonomous"] is True
    assert params["max_iterations"] == 9


@pytest.mark.asyncio
async def test_daemon_logs_thread_to_file(tmp_path: Any) -> None:
    """Test that daemon logs user input and assistant responses to thread file."""
    from soothe.logging import ThreadLogger

    daemon = SootheDaemon(SootheConfig())
    fake_runner = _FakeRunnerWithMessages()
    daemon._runner = fake_runner  # type: ignore[attr-defined]
    daemon._runner_factory = _FakeRunnerFactory(fake_runner)  # type: ignore[attr-defined]
    daemon._session_manager = SimpleNamespace(  # type: ignore[attr-defined]
        claim_loop_ownership=lambda *_args, **_kwargs: None,
        release_loop_ownership=lambda *_args, **_kwargs: None,
        subscribe_loop=lambda *_args, **_kwargs: True,
        get_stream_delivery=lambda *_args, **_kwargs: "batch",
        await_loop_delivery_drained=AsyncMock(return_value=True),
        get_clients_for_loop=AsyncMock(return_value=[]),  # RFC-450 §9.4
        get_loop_subscription_id=AsyncMock(return_value=None),  # RFC-450 §9.4
    )
    daemon._message_router = SimpleNamespace(  # type: ignore[attr-defined]
        _send_complete=lambda *_args, **_kwargs: None,  # RFC-450 §9.4
    )
    daemon._thread_registry = _FakeThreadRegistry()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Create a thread logger with temp directory
    thread_logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="thread-test")
    daemon._thread_logger = thread_logger

    # Run a query
    await daemon._query_engine.run_query("Hello, assistant", loop_id="loop-u")

    await _await_background_query_idle(daemon, sent)

    # Flush buffered writes before reading
    thread_logger.flush()

    # Verify thread was logged
    records = thread_logger.read_recent_records(limit=20)

    # Should have: user input, custom event, assistant response
    user_inputs = [
        r for r in records if r.get("kind") == "conversation" and r.get("role") == "user"
    ]
    assistant_responses = [
        r for r in records if r.get("kind") == "conversation" and r.get("role") == "assistant"
    ]
    events = [r for r in records if r.get("kind") == "event"]

    assert len(user_inputs) == 1
    assert user_inputs[0].get("text") == "Hello, assistant"

    assert len(assistant_responses) == 1
    assert "Hello from assistant" in assistant_responses[0].get("text", "")

    assert len(events) >= 1  # At least the thread.started event


@pytest.mark.asyncio
async def test_daemon_handles_slash_commands() -> None:
    """Test that daemon executes RPC commands via command_request (RFC-454)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Test /memory RPC command (now uses command_request protocol)
    await daemon._handle_command_request(
        {"type": "command_request", "command": "memory", "loop_id": "loop-1", "params": {}}
    )

    # Should have sent a command_response message
    response_msgs = [msg for msg in sent if msg.get("type") == "command_response"]
    assert len(response_msgs) >= 1

    # The response should contain memory stats
    assert response_msgs[0].get("command") == "memory"
    assert "data" in response_msgs[0]


@pytest.mark.asyncio
async def test_daemon_command_exit_does_not_stop_daemon() -> None:
    """Test that /exit and /quit commands do NOT stop the daemon (IG-085, RFC-0013).

    Per RFC-0013 daemon lifecycle semantics:
    - /exit and /quit should detach client, not stop daemon
    - Only explicit 'soothed stop' should shutdown daemon
    """
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Test /exit RPC command (RFC-454 protocol)
    await daemon._handle_command_request(
        {"type": "command_request", "command": "exit", "loop_id": "loop-1", "params": {}}
    )

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

    await sdk_session.connect_websocket_with_retries(_RetryClient())

    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_connect_with_retries_raises_after_exhaustion(monkeypatch) -> None:
    class _FailingClient:
        async def connect(self) -> None:
            raise FileNotFoundError("missing socket")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(sdk_session, "_CONNECT_RETRY_COUNT", 2)

    with pytest.raises(FileNotFoundError):
        await sdk_session.connect_websocket_with_retries(_FailingClient())


@pytest.mark.asyncio
async def test_websocket_client_wait_for_connection_ack_returns_ready() -> None:
    seq = _SequencedClient(
        events=[
            {"type": "status", "state": "idle", "thread_id": ""},
            {
                "proto": "1",
                "type": "connection_ack",
                "result": {"readiness_state": "ready", "protocol_version": "1"},
            },
        ]
    )
    client = WebSocketClient()
    client._connected = True
    client._read_inbound_event = seq._read_inbound_event  # type: ignore[method-assign]
    client.is_connection_alive = seq.is_connection_alive  # type: ignore[method-assign]

    event = await client.wait_for_connection_ack(ack_timeout_s=0.5)

    assert event["result"]["readiness_state"] == "ready"


@pytest.mark.asyncio
async def test_websocket_client_wait_for_connection_ack_raises_on_error_state() -> None:
    seq = _SequencedClient(
        events=[
            {
                "proto": "1",
                "type": "connection_ack",
                "result": {
                    "readiness_state": "error",
                    "server_version": "0.5.0",
                },
            }
        ]
    )
    client = WebSocketClient()
    client._connected = True
    client._read_inbound_event = seq._read_inbound_event  # type: ignore[method-assign]
    client.is_connection_alive = seq.is_connection_alive  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_websocket_client_wait_for_connection_ack_waits_through_warming(monkeypatch) -> None:
    """RFC-450: retry while daemon reports starting/warming instead of failing immediately."""
    seq = _SequencedClient(
        events=[
            {
                "proto": "1",
                "type": "connection_ack",
                "result": {"readiness_state": "warming", "protocol_version": "1"},
            },
            {
                "proto": "1",
                "type": "connection_ack",
                "result": {"readiness_state": "ready", "protocol_version": "1"},
            },
        ]
    )
    client = WebSocketClient()
    client._connected = True
    client._read_inbound_event = seq._read_inbound_event  # type: ignore[method-assign]
    client.is_connection_alive = seq.is_connection_alive  # type: ignore[method-assign]
    repoll_calls = {"n": 0}

    async def _request_connection_init() -> None:
        repoll_calls["n"] += 1

    client.request_connection_init = _request_connection_init  # type: ignore[method-assign]

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    event = await client.wait_for_connection_ack(ack_timeout_s=0.5)

    assert event["result"]["readiness_state"] == "ready"
    assert repoll_calls["n"] == 1


@pytest.mark.asyncio
async def test_daemon_run_query_broadcasts_idle_to_original_thread() -> None:
    daemon = SootheDaemon(SootheConfig())
    fake_runner = _FakeRunnerThatSwapsThread()
    daemon._runner = fake_runner  # type: ignore[attr-defined]
    daemon._runner_factory = _FakeRunnerFactory(fake_runner)  # type: ignore[attr-defined]

    sent: list[dict[str, Any]] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]
    await daemon._query_engine.run_query("analyze project structure", loop_id="loop-u")

    status_messages = await _await_background_query_idle(daemon, sent)
    assert status_messages[0]["state"] == "running"
    assert status_messages[0]["loop_id"] == "loop-u"
    assert status_messages[-1]["state"] == "idle"
    assert status_messages[-1]["loop_id"] == "loop-u"


@pytest.mark.asyncio
async def test_run_headless_via_daemon_returns_direct_error_before_query_start(monkeypatch) -> None:
    post_bootstrap = iter([{"type": "error", "code": "DAEMON_BUSY", "message": "busy"}])

    class _BusyClient:
        async def connect(self) -> None:
            return None

        async def request_connection_init(self) -> None:
            return None

        async def wait_for_connection_ack(self, ack_timeout_s: float = 10.0) -> dict[str, Any]:
            return {"type": "connection_ack", "result": {"readiness_state": "ready"}}

        async def request_response(
            self,
            payload: dict[str, Any],
            *,
            response_type: str,
            timeout: float,
        ) -> dict[str, Any]:
            req_id = payload.get("request_id")
            if payload.get("type") == "loop_new":
                return {"type": "loop_new_response", "loop_id": "loop-123", "request_id": req_id}
            if payload.get("type") == "loop_subscribe":
                return {"type": "loop_subscribe_response", "success": True, "request_id": req_id}
            msg = f"unexpected request_response payload {payload!r}"
            raise AssertionError(msg)

        async def request(
            self,
            method: str,
            params: dict[str, Any],
            *,
            timeout: float = 5.0,
        ) -> dict[str, Any]:
            # Protocol-1 request returns the result dict directly (not wrapped).
            if method == "loop_new":
                return {"loop_id": "loop-123"}
            if method == "loop_reattach":
                return {"loop_id": params.get("loop_id", "loop-123")}
            msg = f"unexpected request method {method!r}"
            raise AssertionError(msg)

        async def subscribe(
            self,
            method: str,
            params: dict[str, Any],
            *,
            timeout: float = 5.0,
        ) -> str:
            return "sub-1"

        async def notify(
            self,
            method: str,
            params: dict[str, Any],
            *,
            receipt: str | None = None,
        ) -> None:
            return None

        async def send_input(
            self,
            _loop_id: str,
            _text: str,
            *,
            autonomous: bool = False,  # noqa: FBT001, FBT002
            max_iterations: int | None = None,
            preferred_subagent: str | None = None,
        ) -> None:
            return None

        async def read_event(self) -> dict[str, Any] | None:
            return next(post_bootstrap, None)

        async def close(self) -> None:
            return None

    stderr: list[str] = []

    # Patch WebSocketClient where it's imported by daemon.py
    # daemon.py imports: from soothe_sdk.client import WebSocketClient
    # So we patch soothe_sdk.client.WebSocketClient (not websocket.WebSocketClient)
    monkeypatch.setattr("soothe_sdk.client.WebSocketClient", lambda url=None: _BusyClient())
    monkeypatch.setattr(
        typer, "echo", lambda msg, err=False: stderr.append(str(msg)) if err else None
    )

    # Use CLIConfig which has daemon_host/daemon_port for websocket_url_from_config
    from soothe_cli.config.cli_config import CLIConfig

    cli_cfg = CLIConfig()
    code = await daemon_exec.run_headless_via_daemon(cli_cfg, "analyze project structure")

    assert code == 1
    assert stderr == ["ERROR: busy"]


def test_run_headless_stops_stale_daemon_before_restart(monkeypatch) -> None:
    """Test that headless stops stale daemon before restart (RFC-0013 WebSocket lifecycle).

    After IG-174/IG-175 refactoring, headless.py uses WebSocket RPC checks instead
    of SootheDaemon static methods. The flow is:
    1. is_daemon_live() returns False (daemon not responsive)
    2. WebSocketClient is created and request_daemon_shutdown() is called
    3. Daemon is started via subprocess
    """
    from soothe_cli.config.cli_config import CLIConfig

    cfg = CLIConfig()
    shutdown_called = MagicMock()
    captured_coros: list[object] = []
    subprocess_popen = MagicMock()

    # Mock WebSocketClient instance with connect/close methods
    mock_client_instance = MagicMock()
    mock_client_instance.connect = AsyncMock()
    mock_client_instance.close = AsyncMock()

    # Patch SDK client helpers (WebSocket RPC checks).
    # First call: pipeline decides daemon is not live (stale path). Second call:
    # readiness loop sees daemon ready — avoids real asyncio.sleep + 30s timeout.
    monkeypatch.setattr(
        "soothe_cli.cli.execution.headless.is_daemon_live",
        AsyncMock(side_effect=[False, True]),
    )
    monkeypatch.setattr(
        "soothe_cli.cli.execution.headless.request_daemon_shutdown",
        AsyncMock(side_effect=lambda client, timeout: shutdown_called()),
    )
    monkeypatch.setattr(
        "soothe_cli.cli.execution.headless.WebSocketClient",
        MagicMock(return_value=mock_client_instance),  # Return mock instance
    )
    monkeypatch.setattr(
        "soothe_cli.cli.execution.daemon.run_headless_via_daemon",
        AsyncMock(return_value=0),
    )

    # run_headless uses a single asyncio.run(_run_headless_pipeline()); run the coroutine
    # on a fresh loop and return its exit code (mirroring asyncio.run).
    def _fake_asyncio_run(coro: object) -> object:
        captured_coros.append(coro)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr("asyncio.run", _fake_asyncio_run)
    monkeypatch.setattr("subprocess.Popen", subprocess_popen)
    monkeypatch.setattr(
        headless_exec.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code))
    )

    with pytest.raises(SystemExit) as exc:
        headless_exec.run_headless(cfg, "analyze project structure")

    assert exc.value.code == 0
    shutdown_called.assert_called_once()  # Stale daemon cleanup called
    subprocess_popen.assert_called_once()  # Daemon restart via subprocess
    assert len(captured_coros) == 1
    assert captured_coros[0].cr_code.co_name == "_run_headless_pipeline"
    # Close coroutines to avoid warnings
    for coro in captured_coros:
        if hasattr(coro, "close"):
            coro.close()


@pytest.mark.asyncio
async def test_daemon_ready_request_replies_without_session() -> None:
    daemon = SootheDaemon(SootheConfig())
    daemon._session_manager = SimpleNamespace(get_session=AsyncMock(return_value=None))  # type: ignore[attr-defined]

    sent: list[dict[str, Any]] = []

    async def _fake_send_client_message(client_id: Any, msg: dict[str, Any]) -> None:
        assert client_id == "client-handshake"
        sent.append(msg)

    daemon._send_client_message = _fake_send_client_message  # type: ignore[method-assign]
    daemon._readiness_state = "ready"
    daemon._readiness_message = None

    await daemon._handle_client_message(
        "client-handshake",
        {
            "proto": "1",
            "type": "connection_init",
            "params": {
                "client_version": "test",
                "accept_proto": ["1"],
                "capabilities": ["streaming", "batch", "heartbeat"],
            },
        },
    )

    assert len(sent) == 1
    ack = sent[0]
    assert ack["type"] == "connection_ack"
    assert ack["result"]["readiness_state"] == "ready"


@pytest.mark.asyncio
async def test_detach_ignores_connection_loss_for_transport_session() -> None:
    daemon = SootheDaemon(SootheConfig())
    transport = SimpleNamespace(send=AsyncMock(side_effect=ConnectionError("Connection lost")))
    transport_client = SimpleNamespace()  # Mock transport client
    session = SimpleNamespace(transport=transport, transport_client=transport_client)

    async def _send_to_client(s: Any, msg: dict[str, Any]) -> None:
        await s.transport.send(msg)

    daemon._session_manager = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        send_to_client=_send_to_client,
    )  # type: ignore[attr-defined]
    _mark_handshake(daemon)

    await daemon._handle_client_message(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "disconnect",
            "params": {},
        },
    )

    transport.send.assert_awaited_once()
