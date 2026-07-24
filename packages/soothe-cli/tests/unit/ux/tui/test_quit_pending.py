"""Tests for Ctrl+C and Ctrl+D interrupt/exit hints."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.app._module_init import QueuedMessage


def test_ctrl_c_idle_clears_input_and_shows_quit_command_hint() -> None:
    """Ctrl+C when idle should not arm quit; it hints `/quit` instead."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "some draft text"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = False
            self._shell_worker = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    app._chat_input.clear_input.assert_called_once()
    app.notify.assert_called_once()
    assert "exit, quit, or /quit" in app.notify.call_args.args[0]


def test_ctrl_c_clears_input_first_when_agent_running() -> None:
    """First Ctrl+C with pending input should clear input, not interrupt agent."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "draft text"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
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


def test_ctrl_c_interrupts_agent_when_input_empty() -> None:
    """Ctrl+C with empty input should interrupt running agent."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
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
    if app.run_worker.call_args:
        app.run_worker.call_args[0][0].close()

    # Should cancel worker, NOT clear input (already empty)
    app._chat_input.clear_input.assert_not_called()
    app._agent_worker.cancel.assert_called_once()


def test_ctrl_c_clears_input_first_when_shell_running() -> None:
    """First Ctrl+C with pending input should clear input, not kill shell."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = "draft"
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
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


def test_ctrl_c_interrupts_shell_when_input_empty() -> None:
    """Ctrl+C with empty input should kill running shell."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
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


def test_ctrl_c_clears_input_when_in_command_mode() -> None:
    """Ctrl+C should clear input when in command/shell mode (non-normal)."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""  # Empty text but in command mode
            # Use PropertyMock for mode since it's checked via != "normal"
            type(self._chat_input).mode = PropertyMock(return_value="command")
            self._chat_input._current_suggestions = []
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


def test_double_ctrl_c_no_longer_quits_when_idle() -> None:
    """Ctrl+C never exits; it should keep hinting `/quit`."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._agent_running = False
            self._agent_worker = None
            self._shell_running = False
            self._shell_worker = None
            self.notify = MagicMock()
            self.set_timer = MagicMock()
            self._detach_or_exit = MagicMock()

    app = _AppStub()
    app.action_quit_or_interrupt()

    app._detach_or_exit.assert_not_called()
    app._chat_input.clear_input.assert_called_once()
    app.notify.assert_called_once()
    assert "exit, quit, or /quit" in app.notify.call_args.args[0]


def test_ctrl_d_hints_use_quit_command() -> None:
    """Ctrl+D should not exit directly; it should hint explicit slash exit."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self.notify = MagicMock()
            self._detach_or_exit = MagicMock()

    app = _AppStub()
    app.action_quit_app()

    app._detach_or_exit.assert_not_called()
    app.notify.assert_called_once()
    assert "exit, quit, or /quit" in app.notify.call_args.args[0]


def test_ctrl_c_preserves_queued_goal_when_interrupting_agent() -> None:
    """Ctrl+C should cancel the running goal only, not discard queued goals."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
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
    if app.run_worker.call_args:
        app.run_worker.call_args[0][0].close()

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
    coro.close()
    assert len(app._pending_messages) == 1


@pytest.mark.asyncio
async def test_interrupt_daemon_turn_preserves_queue_when_requested() -> None:
    """Queue-preserving daemon interrupt keeps queue and local worker alive."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._daemon_session = AsyncMock()
            self._agent_worker = MagicMock()
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._queued_widgets = deque()
            self._deferred_actions = []
            self._set_spinner = AsyncMock()

    app = _AppStub()
    await app._interrupt_daemon_agent_turn(discard_queue=False)

    app._daemon_session.cancel_remote_query.assert_awaited_once()
    app._agent_worker.cancel.assert_not_called()
    assert len(app._pending_messages) == 1


@pytest.mark.asyncio
async def test_interrupt_daemon_turn_cancels_worker_when_remote_cancel_fails() -> None:
    """Fallback to local worker cancel when daemon /cancel cannot be sent."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._daemon_session = AsyncMock()
            self._daemon_session.cancel_remote_query.side_effect = RuntimeError("boom")
            self._agent_worker = MagicMock()
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._queued_widgets = deque()
            self._deferred_actions = []
            self._set_spinner = AsyncMock()

    app = _AppStub()
    await app._interrupt_daemon_agent_turn(discard_queue=False)

    app._daemon_session.cancel_remote_query.assert_awaited_once()
    app._agent_worker.cancel.assert_called_once()
    assert len(app._pending_messages) == 1


def test_can_run_queued_goal_now_from_enter_requires_normal_queue_head() -> None:
    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._agent_running = True
            self._pending_messages = deque([QueuedMessage(text="/help", mode="command")])

    app = _AppStub()
    assert app._can_run_queued_goal_now_from_enter() is False
    app._pending_messages = deque([QueuedMessage(text="next", mode="normal")])
    assert app._can_run_queued_goal_now_from_enter() is True


def test_enter_shortcut_interrupts_running_goal_via_daemon_path() -> None:
    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._agent_running = True
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._agent_worker = MagicMock()
            self._daemon_session = MagicMock()
            self.run_worker = MagicMock()

    app = _AppStub()
    assert app.run_queued_goal_now_from_enter() is True

    app.run_worker.assert_called_once()
    coro = app.run_worker.call_args[0][0]
    assert coro.cr_code.co_name == "_interrupt_daemon_agent_turn"
    coro.close()
    assert len(app._pending_messages) == 1


def test_enter_shortcut_interrupts_running_goal_without_daemon() -> None:
    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._chat_input = MagicMock()
            self._chat_input.value = ""
            self._chat_input.mode = "normal"
            self._chat_input._current_suggestions = []
            self._agent_running = True
            self._pending_messages = deque([QueuedMessage(text="queued", mode="normal")])
            self._agent_worker = MagicMock()
            self._daemon_session = None
            self.run_worker = MagicMock()

    app = _AppStub()
    assert app.run_queued_goal_now_from_enter() is True

    app.run_worker.assert_called_once()
    coro = app.run_worker.call_args[0][0]
    assert coro.cr_code.co_name == "_tear_down_interrupt_ui"
    coro.close()
    app._agent_worker.cancel.assert_called_once()
    assert len(app._pending_messages) == 1
