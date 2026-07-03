"""Tests for Escape — UI dismiss only (no agent/shell interrupt)."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

from soothe_cli.tui.app._messages_mixin import _MessagesMixin


def test_esc_does_not_interrupt_running_agent() -> None:
    """Escape must not cancel an in-flight agent turn."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self.screen = MagicMock()
            self.screen.is_modal = False
            self._chat_input = MagicMock()
            self._chat_input.dismiss_completion.return_value = False
            self._chat_input.exit_mode.return_value = False
            self._plan_quick_view_overlay = None
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._daemon_session = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._pending_messages = deque(["queued goal"])
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_dismiss_ui()

    app.run_worker.assert_not_called()


def test_esc_does_not_kill_running_shell() -> None:
    """Escape must not cancel a running shell command."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self.screen = MagicMock()
            self.screen.is_modal = False
            self._chat_input = MagicMock()
            self._chat_input.dismiss_completion.return_value = False
            self._chat_input.exit_mode.return_value = False
            self._plan_quick_view_overlay = None
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = True
            self._shell_worker = MagicMock()
            self._cancel_worker = MagicMock()

    app = _AppStub()
    app.action_dismiss_ui()

    app._cancel_worker.assert_not_called()


def test_esc_collapses_plan_quick_view_overlay() -> None:
    """Escape closes the expanded plan quick-view panel."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self.screen = MagicMock()
            self.screen.is_modal = False
            self._chat_input = MagicMock()
            self._chat_input.dismiss_completion.return_value = False
            self._chat_input.exit_mode.return_value = False
            overlay = MagicMock()
            overlay.is_expanded = True
            self._plan_quick_view_overlay = overlay

    app = _AppStub()
    app.action_dismiss_ui()

    app._plan_quick_view_overlay.collapse.assert_called_once()
