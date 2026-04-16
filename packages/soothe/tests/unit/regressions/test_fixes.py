"""Tests for the three critical bug fixes."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT
from soothe.daemon import SootheDaemon, WebSocketClient
from soothe.daemon.thread_state import ThreadStateRegistry
from soothe.foundation.slash_commands import (
    _show_memory,
    handle_slash_command,
)
from soothe_cli.cli.stream import StreamDisplayPipeline
from soothe_cli.shared.essential_events import is_essential_progress_event_type
from soothe_cli.tui.textual_adapter import (
    _extract_custom_output_text,
    _format_progress_event_lines_for_tui,
)

# ---------------------------------------------------------------------------
# Fix 1: TUI Slash Commands Not Working (async issue)
# ---------------------------------------------------------------------------


def test_show_memory_is_async() -> None:
    """Verify _show_memory is an async function."""
    assert inspect.iscoroutinefunction(_show_memory), "_show_memory should be async"


def test_handle_slash_command_is_async() -> None:
    """Verify handle_slash_command is an async function."""
    assert inspect.iscoroutinefunction(handle_slash_command), "handle_slash_command should be async"


@pytest.mark.asyncio
async def test_show_memory_calls_await() -> None:
    """Test that _show_memory properly awaits the runner."""
    from io import StringIO

    from rich.console import Console

    class FakeRunner:
        async def memory_stats(self) -> dict:
            return {"test": "data"}

    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    runner = FakeRunner()

    # This should work without raising RuntimeError about nested event loops
    await _show_memory(console, runner)

    result = output.getvalue()
    assert "Memory Stats" in result
    assert "test" in result


# ---------------------------------------------------------------------------
# Fix 2: CLI Thread List Command Hangs
# ---------------------------------------------------------------------------


def test_thread_list_via_daemon_uses_thread_list_protocol() -> None:
    """Daemon-backed list must not exit on handshake ``status`` idle (see IG / thread_cmd)."""
    from soothe_cli.cli.commands.thread_cmd import _thread_list_via_daemon

    source = inspect.getsource(_thread_list_via_daemon)
    assert "thread_list_response" in source
    assert "send_thread_list" in source
    assert "asyncio.timeout" in source
    # Regression: first WS message is often status idle; breaking there printed nothing.
    assert 'if state in ("idle", "stopped")' not in source


def test_thread_status_matches_cli_filter() -> None:
    from soothe_cli.cli.commands.thread_cmd import _thread_status_matches_cli_filter

    assert _thread_status_matches_cli_filter("idle", None) is True
    assert _thread_status_matches_cli_filter("idle", "active") is True
    assert _thread_status_matches_cli_filter("running", "active") is True
    assert _thread_status_matches_cli_filter("archived", "active") is False
    assert _thread_status_matches_cli_filter("archived", "archived") is True


# ---------------------------------------------------------------------------
# Fix 3: Thread Continue Command with --daemon flag (RFC-402)
# ---------------------------------------------------------------------------


def test_thread_continue_requires_daemon() -> None:
    """Test that thread continue command requires running daemon."""
    import inspect

    from soothe_cli.cli.commands.thread_cmd import thread_continue

    sig = inspect.signature(thread_continue)
    params = sig.parameters

    # Check that daemon flag has been removed (no longer a parameter)
    assert "daemon" not in params, "thread_continue should NOT have daemon parameter (deprecated)"

    # Check for new flag (should still exist)
    assert "new" in params, "thread_continue should have new parameter"

    # Check the function docstring mentions daemon requirement
    docstring = thread_continue.__doc__
    assert docstring is not None
    assert "daemon" in docstring.lower(), "Docstring should mention daemon requirement"


@pytest.mark.asyncio
async def test_daemon_handles_resume_thread_message() -> None:
    """Test that daemon handles resume_thread message type."""
    from unittest.mock import AsyncMock

    from soothe.config import SootheConfig

    daemon = SootheDaemon(SootheConfig())

    class FakeRunner:
        def __init__(self) -> None:
            self.current_thread_id = ""
            self.set_thread_id_calls: list[str] = []
            self._durability = MagicMock()
            self.resume_persisted_thread = AsyncMock(return_value=SimpleNamespace(thread_id="thread-456"))

        def set_current_thread_id(self, thread_id: str) -> None:
            self.set_thread_id_calls.append(thread_id)
            self.current_thread_id = thread_id

    daemon._runner = FakeRunner()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Mock session manager to return None (no active session)
    daemon._session_manager.get_session = AsyncMock(return_value=None)  # type: ignore[method-assign]

    await daemon._handle_client_message("test-client-id", {"type": "resume_thread", "thread_id": "thread-456"})

    daemon._runner.resume_persisted_thread.assert_awaited_once_with("thread-456")  # type: ignore[attr-defined]

    # Verify runner's thread_id was set
    assert "thread-456" in daemon._runner.set_thread_id_calls  # type: ignore[attr-defined]

    # Note: Status is not broadcast when no session exists
    # (It would be sent directly to the session if one existed)


@pytest.mark.asyncio
async def test_daemon_run_query_persists_assistant_from_custom_output() -> None:
    """Ensure daemon persists assistant text emitted via custom output events."""
    from soothe.config import SootheConfig

    daemon = SootheDaemon(SootheConfig())

    class _Store:
        def load(self, _key: str) -> None:
            return None

        def save(self, _key: str, _value: dict) -> None:
            return None

    class FakeRunner:
        def __init__(self) -> None:
            self.current_thread_id = "thread-456"
            self._durability = SimpleNamespace(_store=_Store())

        async def astream(self, _text: str, **_kwargs: Any):
            yield ((), "custom", {"type": CHITCHAT_RESPONSE, "content": "hello from custom output"})

        async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
            return None

    daemon._runner = FakeRunner()  # type: ignore[assignment]

    logger_mock = MagicMock()
    logger_mock._thread_id = "thread-456"
    logger_mock.log = MagicMock()
    logger_mock.log_user_input = MagicMock()
    logger_mock.log_assistant_response = MagicMock()
    daemon._thread_logger = logger_mock

    # Mock thread_registry with per-thread input history for query_engine
    reg = ThreadStateRegistry()
    reg.ensure("thread-456")
    daemon._thread_registry = reg  # type: ignore[attr-defined]

    async def _fake_broadcast(_msg: dict[str, Any]) -> None:
        return None

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    await daemon._run_query("hi")

    logger_mock.log_assistant_response.assert_called_once()
    persisted_text = logger_mock.log_assistant_response.call_args.args[0]
    assert "hello from custom output" in persisted_text


@pytest.mark.asyncio
async def test_websocket_client_send_resume_thread() -> None:
    """Test that WebSocketClient sends resume_thread with workspace (replaces deprecated DaemonClient)."""
    client = WebSocketClient()
    captured: list[dict] = []

    async def _fake_send(payload: dict) -> None:
        captured.append(payload)

    client._connected = True
    client.send = _fake_send  # type: ignore[method-assign]
    await client.send_resume_thread("thread-789")

    # Protocol now includes workspace field
    assert len(captured) == 1
    assert captured[0]["type"] == "resume_thread"
    assert captured[0]["thread_id"] == "thread-789"
    assert "workspace" in captured[0]  # Workspace is now sent


@pytest.mark.asyncio
async def test_daemon_handles_new_thread_message_creates_thread() -> None:
    """new_thread should allocate a concrete thread ID immediately."""
    from unittest.mock import AsyncMock

    from soothe.config import SootheConfig

    daemon = SootheDaemon(SootheConfig())

    class FakeRunner:
        def __init__(self) -> None:
            self.current_thread_id = ""
            self.set_thread_id_calls: list[str] = []
            self._durability = MagicMock()

        def set_current_thread_id(self, thread_id: str) -> None:
            self.set_thread_id_calls.append(thread_id)
            self.current_thread_id = thread_id

    daemon._runner = FakeRunner()  # type: ignore[attr-defined]

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Mock session manager to return None (no active session)
    daemon._session_manager.get_session = AsyncMock(return_value=None)  # type: ignore[method-assign]

    await daemon._handle_client_message("test-client-id", {"type": "new_thread"})

    # Verify draft thread was created (not persisted yet) — IG-110: tracked in registry
    tid = daemon._runner.current_thread_id
    assert tid
    reg = daemon._thread_registry.get(tid)
    assert reg is not None and reg.is_draft

    # Note: Status is not broadcast when no session exists
    # (It would be sent directly to the session if one existed)


@pytest.mark.asyncio
async def test_slash_command_memory_in_daemon() -> None:
    """Test that /memory command works in daemon context (no nested event loops)."""
    from io import StringIO

    from rich.console import Console

    class FakeRunner:
        async def memory_stats(self) -> dict:
            return {"backend": "test", "entries": 5}

    runner = FakeRunner()
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)

    # This should work without RuntimeError about nested event loops
    result = await handle_slash_command(
        "/memory", runner, console, current_plan=None, thread_logger=None, input_history=None
    )

    assert result is False  # Should not exit
    assert "Memory Stats" in output.getvalue()
    assert "backend" in output.getvalue()


@pytest.mark.asyncio
async def test_slash_command_context_in_daemon() -> None:
    """Test that /context command returns message about removal."""
    from io import StringIO

    from rich.console import Console

    runner = MagicMock()
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)

    # /context should now return a message about removal
    result = await handle_slash_command(
        "/context", runner, console, current_plan=None, thread_logger=None, input_history=None
    )

    assert result is False  # Should not exit
    raw = output.getvalue()
    # Strip ANSI escape codes for assertion
    import re

    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    assert "Context protocol removed" in clean
    assert "/memory" in clean


@pytest.mark.asyncio
async def test_slash_command_thread_archive_in_daemon() -> None:
    """Test that /thread archive command works in daemon context (no nested event loops)."""
    from io import StringIO

    from rich.console import Console

    class FakeDurability:
        def __init__(self) -> None:
            self.archived: list[str] = []

        async def archive_thread(self, thread_id: str) -> None:
            self.archived.append(thread_id)

    class FakeRunner:
        def __init__(self) -> None:
            self._durability = FakeDurability()

    runner = FakeRunner()
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)

    # This should work without RuntimeError about nested event loops
    result = await handle_slash_command(
        "/thread archive test-thread-id",
        runner,
        console,
        current_plan=None,
        thread_logger=None,
        input_history=None,
    )

    assert result is False  # Should not exit
    assert "test-thread-id" in runner._durability.archived
    assert "Archived thread test-thread-id" in output.getvalue()


def test_tui_extract_custom_output_text_accepts_final_report_summary() -> None:
    """Final-report summary payloads are rendered in the TUI."""
    output_text = _extract_custom_output_text(
        {
            "type": FINAL_REPORT,
            "summary": "This is the final report summary.",
        }
    )
    assert output_text == "This is the final report summary."


def test_tui_extract_custom_output_text_accepts_final_report_content() -> None:
    """Final-report content payloads are also rendered in the TUI."""
    output_text = _extract_custom_output_text(
        {
            "type": FINAL_REPORT,
            "content": "This is the final report content.",
        }
    )
    assert output_text == "This is the final report content."


def test_tui_extract_custom_output_text_accepts_agent_loop_completed_final_stdout() -> None:
    """Agent-loop completed event final stdout should render in TUI."""
    output_text = _extract_custom_output_text(
        {
            "type": "soothe.cognition.agent_loop.completed",
            "final_stdout_message": "Final report body from completed event.",
        }
    )
    assert output_text == "Final report body from completed event."


def test_tui_formats_goal_progress_like_cli() -> None:
    """Goal progress events should render through the shared CLI pipeline format."""
    pipeline = StreamDisplayPipeline(verbosity="normal")
    lines = _format_progress_event_lines_for_tui(
        {"type": "soothe.cognition.agent_loop.started", "goal": "Investigate daemon gap"},
        (),
        pipeline=pipeline,
    )
    assert lines
    assert any("🚩 Investigate daemon gap" in line for line in lines)


def test_shared_essential_progress_event_filter_contract() -> None:
    """Shared filter should include core progress events and exclude non-progress output."""
    assert is_essential_progress_event_type("soothe.cognition.agent_loop.started")
    assert is_essential_progress_event_type("soothe.cognition.agent_loop.reason")
    assert is_essential_progress_event_type("soothe.cognition.plan.step_completed")
    assert not is_essential_progress_event_type("soothe.output.autonomous.final_report")


def test_tui_formats_agent_loop_reason_and_reasoning_like_cli() -> None:
    """Agent-loop reason events should show next_action and reasoning text."""
    pipeline = StreamDisplayPipeline(verbosity="normal")
    lines = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.cognition.agent_loop.reason",
            "status": "working",
            "next_action": "inspect websocket custom events",
            "reasoning": "Need to verify display path parity with CLI.",
        },
        (),
        pipeline=pipeline,
    )
    assert any("🌀 Inspect websocket custom events" in line for line in lines)
    assert any("💭 Reasoning: Need to verify display path parity with CLI." in line for line in lines)


def test_tui_formats_step_start_and_complete_like_cli() -> None:
    """Step start/complete events should map to CLI-style progress lines."""
    pipeline = StreamDisplayPipeline(verbosity="detailed")
    started = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.cognition.plan.step_started",
            "step_id": "s1",
            "description": "Gather daemon custom events",
        },
        (),
        pipeline=pipeline,
    )
    completed = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.cognition.plan.step_completed",
            "step_id": "s1",
            "duration_ms": 1200,
        },
        (),
        pipeline=pipeline,
    )
    assert any("⏩ Gather daemon custom events" in line for line in started)
    assert any("✅ Gather daemon custom events" in line for line in completed)
