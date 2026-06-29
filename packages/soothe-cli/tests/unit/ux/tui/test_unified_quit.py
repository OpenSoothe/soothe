"""Tests for unified TUI quit paths (Ctrl+D, double Ctrl+C, /quit)."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.app import App

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.app._messages_mixin import _MessagesMixin


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


def test_soothe_app_exit_delegates_to_mixin() -> None:
    """``SootheApp.exit`` must invoke mixin teardown (MRO fix)."""
    from soothe_cli.tui.app._app import SootheApp

    assert SootheApp.exit is not App.exit
