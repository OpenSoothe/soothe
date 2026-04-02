"""Tests for the three critical bug fixes."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.core.event_catalog import CHITCHAT_RESPONSE
from soothe.daemon import DaemonClient, SootheDaemon
from soothe.foundation.slash_commands import (
    _show_context,
    _show_memory,
    handle_slash_command,
)

# ---------------------------------------------------------------------------
# Fix 1: TUI Slash Commands Not Working (async issue)
# ---------------------------------------------------------------------------


def test_show_memory_is_async() -> None:
    """Verify _show_memory is an async function."""
    assert inspect.iscoroutinefunction(_show_memory), "_show_memory should be async"


def test_show_context_is_async() -> None:
    """Verify _show_context is an async function."""
    assert inspect.iscoroutinefunction(_show_context), "_show_context should be async"


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


@pytest.mark.asyncio
async def test_show_context_calls_await() -> None:
    """Test that _show_context properly awaits the runner."""
    from io import StringIO

    from rich.console import Console

    class FakeRunner:
        async def context_stats(self) -> dict:
            return {"context": "stats"}

    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    runner = FakeRunner()

    # This should work without raising RuntimeError about nested event loops
    await _show_context(console, runner)

    result = output.getvalue()
    assert "Context Stats" in result
    assert "context" in result


# ---------------------------------------------------------------------------
# Fix 2: CLI Thread List Command Hangs
# ---------------------------------------------------------------------------


def test_thread_list_via_daemon_uses_thread_list_protocol() -> None:
    """Daemon-backed list must not exit on handshake ``status`` idle (see IG / thread_cmd)."""
    from soothe.ux.cli.commands.thread_cmd import _thread_list_via_daemon

    source = inspect.getsource(_thread_list_via_daemon)
    assert "thread_list_response" in source
    assert "send_thread_list" in source
    assert "asyncio.timeout" in source
    # Regression: first WS message is often status idle; breaking there printed nothing.
    assert 'if state in ("idle", "stopped")' not in source


def test_thread_status_matches_cli_filter() -> None:
    from soothe.ux.cli.commands.thread_cmd import _thread_status_matches_cli_filter

    assert _thread_status_matches_cli_filter("idle", None) is True
    assert _thread_status_matches_cli_filter("idle", "active") is True
    assert _thread_status_matches_cli_filter("running", "active") is True
    assert _thread_status_matches_cli_filter("archived", "active") is False
    assert _thread_status_matches_cli_filter("archived", "archived") is True


# ---------------------------------------------------------------------------
# Fix 3: Thread Continue Command with --daemon flag (RFC-0017)
# ---------------------------------------------------------------------------


def test_thread_continue_requires_daemon() -> None:
    """Test that thread continue command requires running daemon."""
    import inspect

    from soothe.ux.cli.commands.thread_cmd import thread_continue

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
    daemon._input_history = None

    async def _fake_broadcast(_msg: dict[str, Any]) -> None:
        return None

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    await daemon._run_query("hi")

    logger_mock.log_assistant_response.assert_called_once()
    persisted_text = logger_mock.log_assistant_response.call_args.args[0]
    assert "hello from custom output" in persisted_text


@pytest.mark.asyncio
async def test_daemon_client_send_resume_thread() -> None:
    """Test that DaemonClient has send_resume_thread method."""
    client = DaemonClient()
    captured: list[dict] = []

    async def _fake_send(payload: dict) -> None:
        captured.append(payload)

    # Set connected state for WebSocketClient
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
async def test_tui_sends_thread_id_on_connection() -> None:
    """Test that TUI passes requested thread id into shared daemon session bootstrap."""
    from soothe.ux.tui import SootheApp

    source = inspect.getsource(SootheApp._connect_and_listen)
    assert "bootstrap_thread_session" in source, "TUI should bootstrap via ux.client.session"
    normalized = "".join(source.split())
    assert "resume_thread_id=self._requested_thread_id" in normalized


def test_process_daemon_event_status_ignores_empty_thread_id() -> None:
    """Empty handshake thread_id must not clear an already selected TUI thread."""
    from dataclasses import dataclass, field
    from typing import Any

    from soothe.ux.shared.event_processor import EventProcessor

    @dataclass
    class MockRenderer:
        calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

        def on_assistant_text(self, text: str, *, is_main: bool, is_streaming: bool) -> None:
            pass

        def on_tool_call(self, name: str, args: dict, tool_call_id: str, *, is_main: bool) -> None:
            pass

        def on_tool_result(self, name: str, result: str, tool_call_id: str, *, is_error: bool, is_main: bool) -> None:
            pass

        def on_status_change(self, state: str) -> None:
            self.calls.append(("on_status_change", (state,), {}))

        def on_error(self, error: str, *, context: str | None = None) -> None:
            pass

        def on_progress_event(self, event_type: str, data: dict, *, namespace: tuple[str, ...]) -> None:
            pass

        def on_plan_created(self, plan: Any) -> None:
            pass

        def on_plan_step_started(self, step_id: str, description: str) -> None:
            pass

        def on_plan_step_completed(self, step_id: str, success: bool, duration_ms: int) -> None:  # noqa: FBT001
            pass

        def on_turn_end(self) -> None:
            pass

    renderer = MockRenderer()
    processor = EventProcessor(renderer)

    # First set a thread_id
    processor.process_event({"type": "status", "state": "running", "thread_id": "thread-keep"})
    assert processor.thread_id == "thread-keep"

    # Empty thread_id should not clear it
    processor.process_event({"type": "status", "state": "idle", "thread_id": ""})
    assert processor.thread_id == "thread-keep"


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
    """Test that /context command works in daemon context (no nested event loops)."""
    from io import StringIO

    from rich.console import Console

    class FakeRunner:
        async def context_stats(self) -> dict:
            return {"backend": "test", "tokens": 1000}

    runner = FakeRunner()
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=100)

    # This should work without RuntimeError about nested event loops
    result = await handle_slash_command(
        "/context", runner, console, current_plan=None, thread_logger=None, input_history=None
    )

    assert result is False  # Should not exit
    assert "Context Stats" in output.getvalue()
    assert "tokens" in output.getvalue()


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
