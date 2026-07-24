"""Tests for unified TUI quit paths (Ctrl+D, double Ctrl+C, /quit, bare exit/quit)."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.app import App

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.widgets.chat_input import ChatInput


class _QuitAppStub(App, _MessagesMixin):
    """Minimal App + mixin stub so ``exit()`` resolves through ``SootheApp`` pattern."""

    def __init__(self) -> None:
        super().__init__()
        self._daemon_session = None
        self._shutdown_prepared = False
        self._exit = False
        self._inflight_turn_stats = None
        self._session_stats = SessionStats()
        self._shell_running = False
        self._shell_worker = None
        self._agent_running = False
        self._agent_worker = None
        self._pending_messages = deque()
        self._queued_widgets = deque()
        self._deferred_actions = []
        self._detaching = False
        self.run_worker = MagicMock()
        self.notify = MagicMock()

    def exit(
        self,
        result=None,
        return_code: int = 0,
        message=None,
    ) -> None:
        _MessagesMixin.exit(self, result=result, return_code=return_code, message=message)


class _SubmitQuitStub(_ExecutionMixin):
    """Minimal execution stub for bare/slash quit submission."""

    def __init__(self) -> None:
        self._loop_switching = False
        self._agent_running = False
        self._shell_running = False
        self._connecting = False
        self._pending_messages = deque()
        self._queued_widgets = deque()
        self._detach_or_exit = MagicMock()
        self._process_message = AsyncMock()


def test_detach_or_exit_without_daemon_calls_textual_exit() -> None:
    """No daemon session: prepare shutdown and exit without detach worker."""
    app = _QuitAppStub()
    with patch.object(App, "exit", autospec=True) as app_exit:
        app._detach_or_exit()

    assert app._exit is True
    assert app._shutdown_prepared is True
    app.run_worker.assert_not_called()
    app_exit.assert_called_once()


@pytest.mark.asyncio
async def test_detach_then_exit_sends_disconnect_and_closes() -> None:
    """Daemon-backed quit worker must detach then fast-close before Textual exit."""
    app = _QuitAppStub()
    app._daemon_session = MagicMock()
    app._daemon_session.detach = AsyncMock()
    app._daemon_session.close = AsyncMock()

    with patch.object(App, "exit", autospec=True) as app_exit:
        await app._detach_then_exit()

    app._daemon_session.detach.assert_awaited_once()
    app._daemon_session.close.assert_awaited_once_with(handshake_timeout=0.3)
    app_exit.assert_called_once()


@pytest.mark.asyncio
async def test_detach_then_exit_still_closes_and_exits_when_detach_raises() -> None:
    """Quit must complete even if detach fails on a dead connection."""
    app = _QuitAppStub()
    app._daemon_session = MagicMock()
    app._daemon_session.detach = AsyncMock(side_effect=ConnectionError("Not connected to daemon"))
    app._daemon_session.close = AsyncMock()

    with patch.object(App, "exit", autospec=True) as app_exit:
        await app._detach_then_exit()

    app._daemon_session.detach.assert_awaited_once()
    app._daemon_session.close.assert_awaited_once_with(handshake_timeout=0.3)
    app_exit.assert_called_once()


def test_soothe_app_exit_delegates_to_mixin() -> None:
    """``SootheApp.exit`` must invoke mixin teardown (MRO fix)."""
    from soothe_cli.tui.app._app import SootheApp

    assert SootheApp.exit is not App.exit


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["exit", "quit", "Exit", " QUIT "])
async def test_bare_quit_word_exits_immediately(word: str) -> None:
    """Single-word exit/quit in normal mode must quit without sending to the agent."""
    app = _SubmitQuitStub()
    event = ChatInput.Submitted(word, mode="normal")

    with patch("soothe_cli.tui.app._execution.dispatch_hook", new_callable=AsyncMock):
        await app.on_chat_input_submitted(event)

    app._detach_or_exit.assert_called_once_with()
    app._process_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["exit please", "please quit", "q"])
async def test_non_exact_quit_text_is_not_bare_quit(text: str) -> None:
    """Only exact single-word exit/quit should trigger bare quit."""
    app = _SubmitQuitStub()
    event = ChatInput.Submitted(text, mode="normal")

    with patch("soothe_cli.tui.app._execution.dispatch_hook", new_callable=AsyncMock):
        await app.on_chat_input_submitted(event)

    app._detach_or_exit.assert_not_called()
    app._process_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", ["/quit", "/q", "/exit"])
async def test_slash_quit_aliases_exit_immediately(cmd: str) -> None:
    """Slash quit aliases must quit immediately in command mode."""
    app = _SubmitQuitStub()
    event = ChatInput.Submitted(cmd, mode="command")

    with patch("soothe_cli.tui.app._execution.dispatch_hook", new_callable=AsyncMock):
        await app.on_chat_input_submitted(event)

    app._detach_or_exit.assert_called_once_with()
    app._process_message.assert_not_awaited()
