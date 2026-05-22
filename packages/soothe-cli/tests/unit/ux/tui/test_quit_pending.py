"""Tests for double-press quit (Ctrl+C) behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.app._messages_mixin import _MessagesMixin


def test_arm_quit_pending_clears_chat_input() -> None:
    """First Ctrl+C should clear draft text while arming the quit hint."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._quit_pending = False
            self.notify = MagicMock()
            self.set_timer = MagicMock()

    app = _AppStub()
    app._arm_quit_pending("Ctrl+C")

    app._chat_input.clear_input.assert_called_once()
    assert app._quit_pending is True
    app.notify.assert_called_once()
