"""Tests for Ctrl+C behavior: clear input → interrupt → quit."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.app._module_init import QueuedMessage


def test_arm_quit_pending_clears_chat_input_when_idle() -> None:
    """First Ctrl+C when idle should clear pending text and arm quit hint."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "some draft text"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = False
            self._shell_worker = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    app._chat_input.clear_input.assert_called_once()
    assert app._quit_pending is True
    app.notify.assert_called_once()


def test_ctrl_c_clears_input_first_when_agent_running() -> None:
    """First Ctrl+C with pending input should clear input, not interrupt agent."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "draft text"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should clear input, NOT cancel worker
    app._chat_input.clear_input.assert_called_once()
    app._agent_worker.cancel.assert_not_called()
    assert app._quit_pending is False


def test_ctrl_c_interrupts_agent_when_input_empty() -> None:
    """Ctrl+C with empty input should interrupt running agent."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = None
            self._pending_messages = []
            self._queued_widgets = []
            self._deferred_actions = []
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should cancel worker, NOT clear input (already empty)
    app._chat_input.clear_input.assert_not_called()
    app._agent_worker.cancel.assert_called_once()
    assert app._quit_pending is False


def test_ctrl_c_clears_input_first_when_shell_running() -> None:
    """First Ctrl+C with pending input should clear input, not kill shell."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "draft"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = True
            self._shell_worker = MagicMock()
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should clear input, NOT cancel worker
    app._chat_input.clear_input.assert_called_once()
    app._shell_worker.cancel.assert_not_called()
    assert app._quit_pending is False


def test_ctrl_c_interrupts_shell_when_input_empty() -> None:
    """Ctrl+C with empty input should kill running shell."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = True
            self._shell_worker = MagicMock()
            self._pending_messages = []
            self._queued_widgets = []
            self._deferred_actions = []
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should cancel worker
    app._chat_input.clear_input.assert_not_called()
    app._shell_worker.cancel.assert_called_once()
    assert app._quit_pending is False


def test_ctrl_c_clears_input_when_in_command_mode() -> None:
    """Ctrl+C should clear input when in command/shell mode (non-normal)."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""  # Empty text but in command mode
            # Use PropertyMock for mode since it's checked via != "normal"
            type(self._chat_input).mode = PropertyMock(return_value="command")
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should clear input (mode != normal counts as pending)
    app._chat_input.clear_input.assert_called_once()
    app._agent_worker.cancel.assert_not_called()


def test_ctrl_c_clears_input_when_completion_active() -> None:
    """Ctrl+C should clear input when completion popup is active."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = [("/help", "Show help")]
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should clear input (completion active counts as pending)
    app._chat_input.clear_input.assert_called_once()
    app._agent_worker.cancel.assert_not_called()


def test_double_ctrl_c_quits_when_idle() -> None:
    """Double Ctrl+C when idle should quit via the unified detach path."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = True  # Already armed from first Ctrl+C
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = False
            self._shell_worker = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self._detach_or_exit = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    # Should use unified quit path, not clear input again
    app._detach_or_exit.assert_called_once()
    app._chat_input.clear_input.assert_not_called()


def test_ctrl_c_preserves_queued_goal_when_interrupting_agent() -> None:
    """Ctrl+C should cancel the running goal only, not discard queued goals."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = None
            self._pending_messages = deque([QueuedMessage(text="next goal", mode="normal")])
            self._queued_widgets = deque()
            self._deferred_actions = []
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    app._agent_worker.cancel.assert_called_once()
    assert len(app._pending_messages) == 1
    assert app._pending_messages[0].text == "next goal"


def test_ctrl_c_preserves_queue_when_interrupting_via_daemon() -> None:
    """Daemon interrupt path should also keep queued goals for post-cancel drain."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._quit_pending = False
            self._agent_running = True
            self._agent_worker = MagicMock()
            self._shell_running = False
            self._shell_worker = None
            self._daemon_session = MagicMock()
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._queued_widgets = deque()
            self._deferred_actions = []
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    app.run_worker.assert_called_once()
    coro = app.run_worker.call_args[0][0]
    assert coro.cr_code.co_name == "_interrupt_daemon_agent_turn"
    assert len(app._pending_messages) == 1


@pytest.mark.asyncio
async def test_interrupt_daemon_turn_preserves_queue_when_requested() -> None:
    """_interrupt_daemon_agent_turn(discard_queue=False) keeps pending messages."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._daemon_session = AsyncMock()
            self._agent_worker = MagicMock()
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._queued_widgets = deque()
            self._deferred_actions = []

    app = _AppStub()
    await app._interrupt_daemon_agent_turn(discard_queue=False)

    app._daemon_session.cancel_remote_query.assert_awaited_once()
    app._agent_worker.cancel.assert_called_once()
    assert len(app._pending_messages) == 1
