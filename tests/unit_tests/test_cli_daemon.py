"""Tests for daemon autonomous propagation and client payloads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

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
        yield ((), "custom", {"type": "soothe.thread.started"})


class _FakeRunnerWithMessages:
    """Runner stub that yields AI messages for session logging tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-test"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        from langchain_core.messages import AIMessage

        self.calls.append({"text": text, **kwargs})

        # Yield a custom event
        yield ((), "custom", {"type": "soothe.thread.started"})

        # Yield a user message marker (not logged)
        yield ((), "custom", {"type": "user.input", "text": text})

        # Yield an AI message with text content
        ai_msg = AIMessage(content="Hello from assistant", id="msg-1")
        yield ((), "messages", (ai_msg, {}))


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
    from soothe.cli.thread_logger import ThreadLogger

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
async def test_daemon_command_exit_stops_daemon() -> None:
    """Test that /exit and /quit commands stop the daemon."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Test /exit command
    await daemon._handle_command("/exit")

    # Should have set running to False
    assert daemon._running is False
    # Should have sent stopping status
    status_msgs = [msg for msg in sent if msg.get("type") == "status"]
    assert any(msg.get("state") == "stopping" for msg in status_msgs)
