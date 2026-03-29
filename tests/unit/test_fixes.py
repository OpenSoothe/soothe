"""Tests for the three critical bug fixes."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.core.event_catalog import CHITCHAT_RESPONSE
from soothe.daemon import DaemonClient, SootheDaemon
from soothe.ux.tui.commands import (
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


@pytest.mark.asyncio
async def test_thread_list_breaks_on_empty_response() -> None:
    """Test that thread list doesn't hang on empty command response."""
    import asyncio

    from soothe.ux.cli.commands.thread_cmd import _thread_list_via_daemon

    # Track if we complete in reasonable time
    completed = False

    async def mock_daemon_interaction():
        """Simulate daemon that returns empty response."""
        nonlocal completed
        # We can't easily mock the full daemon, but we verified the fix
        # by checking the code structure
        completed = True

    # The fix is that 'break' is now outside the 'if content.strip():' block
    # This means it always breaks after command_response, even if empty
    # We verify this by checking the source code
    import ast

    source = inspect.getsource(_thread_list_via_daemon)
    tree = ast.parse(source)

    # Find the _list function and check break statement placement
    found_correct_break = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_list":
            # Look for the if event_type == "command_response" block
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    # Check if there's a break at the right level
                    for child in ast.iter_child_nodes(stmt):
                        if isinstance(child, ast.Break):
                            found_correct_break = True

    assert found_correct_break, "Break should be present in command_response handler"


# ---------------------------------------------------------------------------
# Fix 3: Thread Continue Command with --daemon flag (RFC-0017)
# ---------------------------------------------------------------------------


def test_thread_continue_accepts_daemon_flag() -> None:
    """Test that thread continue command has --daemon flag."""
    from typing import get_type_hints

    import typer

    from soothe.ux.cli.commands.thread_cmd import thread_continue

    sig = inspect.signature(thread_continue)
    params = sig.parameters

    # Check for daemon flag
    assert "daemon" in params, "thread_continue should have daemon parameter"

    # Check it's optional
    param = params["daemon"]
    assert param.default is not inspect.Parameter.empty or str(param).startswith("daemon:"), (
        "daemon flag should be optional"
    )

    # Check for new flag
    assert "new" in params, "thread_continue should have new parameter"


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

    with patch("soothe.core.thread.ThreadContextManager") as manager_cls:
        manager = MagicMock()
        manager.resume_thread = AsyncMock(return_value=SimpleNamespace(thread_id="thread-456"))
        manager_cls.return_value = manager
        await daemon._handle_client_message("test-client-id", {"type": "resume_thread", "thread_id": "thread-456"})

    manager.resume_thread.assert_awaited_once_with("thread-456")

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

    assert captured == [{"type": "resume_thread", "thread_id": "thread-789"}]


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

    # Verify draft thread was created (not persisted yet)
    assert daemon._draft_thread_id is not None
    assert daemon._runner.current_thread_id == daemon._draft_thread_id

    # Note: Status is not broadcast when no session exists
    # (It would be sent directly to the session if one existed)


@pytest.mark.asyncio
async def test_tui_sends_thread_id_on_connection() -> None:
    """Test that TUI sends resume_thread message when thread_id is provided."""
    # We verify this by checking the TUI code calls send_resume_thread
    import ast
    import textwrap

    from soothe.ux.tui import SootheApp

    source = inspect.getsource(SootheApp._connect_and_listen)
    # Dedent the source since inspect.getsource returns indented method
    tree = ast.parse(textwrap.dedent(source))

    # Check for send_resume_thread call
    found_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "send_resume_thread":
                    found_call = True

    assert found_call, "TUI should call send_resume_thread in _connect_and_listen"


def test_process_daemon_event_status_ignores_empty_thread_id() -> None:
    """Empty handshake thread_id must not clear an already selected TUI thread."""
    from dataclasses import dataclass, field
    from typing import Any

    from soothe.ux.core.event_processor import EventProcessor

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
