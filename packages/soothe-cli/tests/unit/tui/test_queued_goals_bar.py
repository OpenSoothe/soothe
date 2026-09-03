"""Tests for the QueuedGoalsBar widget and queued-goal routing.

Covers:
    - Bar renders all queued goals as rows.
    - Bar hides when the queue is empty.
    - Selection navigation (down) clamps at boundaries.
    - Enter triggers submit on the selected goal.
    - Up triggers edit on the selected goal.
    - Esc cancels the selected goal.
    - Index-based cancel/edit/submit on the app mixin.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, PropertyMock, patch

from soothe_cli.display import theme
from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.app._types import QueuedMessage
from soothe_cli.tui.widgets.queued_goals_bar import QueuedGoalsBar

# ---------------------------------------------------------------------------
# Widget-level tests
# ---------------------------------------------------------------------------


def _render_bar(bar: QueuedGoalsBar) -> object:
    """Render a ``QueuedGoalsBar`` with a fixed dark palette (no live app)."""
    colors = theme.DARK_COLORS
    with (
        patch.object(type(bar), "app", new_callable=PropertyMock) as mock_app,
        patch("soothe_cli.display.theme.get_theme_colors", return_value=colors),
    ):
        mock_app.return_value = MagicMock()
        return bar.render()


def test_bar_hides_when_empty() -> None:
    """An empty goals list sets display:none."""
    bar = QueuedGoalsBar()
    bar._goals = []
    bar.set_goals([])
    assert bar.styles.display == "none"
    assert not bar.has_goals


def test_bar_shows_when_non_empty() -> None:
    """A non-empty goals list sets display:block."""
    bar = QueuedGoalsBar()
    goals = [QueuedMessage(text="do thing", mode="normal")]
    bar.set_goals(goals)
    assert bar.styles.display == "block"
    assert bar.has_goals


def test_bar_renders_all_goals() -> None:
    """Multiple queued goals produce multiple rows in the rendered content."""
    bar = QueuedGoalsBar()
    goals = [
        QueuedMessage(text="first goal", mode="normal"),
        QueuedMessage(text="second goal", mode="normal"),
        QueuedMessage(text="third goal", mode="normal"),
    ]
    bar.set_goals(goals)
    content = _render_bar(bar)
    plain = content.plain
    assert "first goal" in plain
    assert "second goal" in plain
    assert "third goal" in plain


def test_bar_selection_clamps_at_boundaries() -> None:
    """Selection cursor clamps at 0 and len-1."""
    bar = QueuedGoalsBar()
    goals = [
        QueuedMessage(text="a", mode="normal"),
        QueuedMessage(text="b", mode="normal"),
        QueuedMessage(text="c", mode="normal"),
    ]
    bar.set_goals(goals)
    assert bar.get_selected_index() == 0

    # Move down past the end — should clamp at last index.
    assert bar.move_selection(5)
    assert bar.get_selected_index() == 2

    # Move up past the start — should clamp at 0.
    assert bar.move_selection(-5)
    assert bar.get_selected_index() == 0

    # Move down by one.
    assert bar.move_selection(1)
    assert bar.get_selected_index() == 1


def test_bar_selection_clamps_when_goals_shrink() -> None:
    """When goals shrink, selection is clamped into the new range."""
    bar = QueuedGoalsBar()
    goals = [
        QueuedMessage(text="a", mode="normal"),
        QueuedMessage(text="b", mode="normal"),
        QueuedMessage(text="c", mode="normal"),
    ]
    bar.set_goals(goals)
    bar.move_selection(2)  # select last
    assert bar.get_selected_index() == 2

    # Shrink to 1 goal — selection should clamp to 0.
    bar.set_goals([QueuedMessage(text="a", mode="normal")])
    assert bar.get_selected_index() == 0


def test_bar_select_and_edit_delegates_to_app() -> None:
    """Up triggers edit_queued_goal_at_index on the app."""
    bar = QueuedGoalsBar()
    bar.set_goals([QueuedMessage(text="edit me", mode="normal")])
    bar.move_selection(0)

    mock_app = MagicMock()
    mock_app.edit_queued_goal_at_index = MagicMock(return_value=True)
    with patch.object(type(bar), "app", new_callable=PropertyMock) as mock_property:
        mock_property.return_value = mock_app
        result = bar.select_and_edit()

    assert result is True
    mock_app.edit_queued_goal_at_index.assert_called_once_with(0)


def test_bar_submit_selected_delegates_to_app() -> None:
    """Enter triggers submit_queued_goal_at_index on the app."""
    bar = QueuedGoalsBar()
    bar.set_goals([QueuedMessage(text="submit me", mode="normal")])
    bar.move_selection(0)

    mock_app = MagicMock()
    mock_app.submit_queued_goal_at_index = MagicMock(return_value=True)
    with patch.object(type(bar), "app", new_callable=PropertyMock) as mock_property:
        mock_property.return_value = mock_app
        result = bar.submit_selected()

    assert result is True
    mock_app.submit_queued_goal_at_index.assert_called_once_with(0)


def test_bar_cancel_selected_delegates_to_app() -> None:
    """Esc triggers cancel_queued_goal_at_index on the app."""
    bar = QueuedGoalsBar()
    bar.set_goals([QueuedMessage(text="cancel me", mode="normal")])
    bar.move_selection(0)

    mock_app = MagicMock()
    mock_app.cancel_queued_goal_at_index = MagicMock(return_value=True)
    with patch.object(type(bar), "app", new_callable=PropertyMock) as mock_property:
        mock_property.return_value = mock_app
        result = bar.cancel_selected()

    assert result is True
    mock_app.cancel_queued_goal_at_index.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# App mixin-level tests
# ---------------------------------------------------------------------------


class _QueueStub(_MessagesMixin):
    """Minimal stub for testing index-based queue operations."""

    def __init__(self) -> None:
        self._pending_messages: deque[QueuedMessage] = deque()
        self._queued_widgets: deque = deque()
        self._chat_input = MagicMock()
        self._chat_input.value = ""
        self._chat_input.mode = "normal"
        self._chat_input._current_suggestions = []
        self.notify = MagicMock()
        self._agent_running = False
        self._shell_running = False
        self._processing_pending = False


def test_cancel_queued_goal_at_index_removes_correct_goal() -> None:
    """Cancelling by index removes exactly that goal from the queue."""
    app = _QueueStub()
    app._pending_messages = deque(
        [
            QueuedMessage(text="first", mode="normal"),
            QueuedMessage(text="second", mode="normal"),
            QueuedMessage(text="third", mode="normal"),
        ]
    )

    result = app.cancel_queued_goal_at_index(1)

    assert result is True
    remaining = list(app._pending_messages)
    assert len(remaining) == 2
    assert remaining[0].text == "first"
    assert remaining[1].text == "third"


def test_cancel_queued_goal_at_index_out_of_range_returns_false() -> None:
    """Out-of-range index returns False without modifying the queue."""
    app = _QueueStub()
    app._pending_messages = deque([QueuedMessage(text="only", mode="normal")])

    assert app.cancel_queued_goal_at_index(5) is False
    assert app.cancel_queued_goal_at_index(-1) is False
    assert len(app._pending_messages) == 1


def test_edit_queued_goal_at_index_moves_to_input() -> None:
    """Editing by index moves the goal text to chat input and removes it."""
    app = _QueueStub()
    app._pending_messages = deque(
        [
            QueuedMessage(text="first", mode="normal"),
            QueuedMessage(text="second", mode="normal"),
        ]
    )

    result = app.edit_queued_goal_at_index(0)

    assert result is True
    assert app._chat_input.value == "first"
    remaining = list(app._pending_messages)
    assert len(remaining) == 1
    assert remaining[0].text == "second"


def test_edit_queued_goal_at_index_skips_non_normal_mode() -> None:
    """Shell/command goals cannot be edited (would clobber input with prefix)."""
    app = _QueueStub()
    app._pending_messages = deque(
        [
            QueuedMessage(text="!ls", mode="shell"),
            QueuedMessage(text="normal goal", mode="normal"),
        ]
    )

    result = app.edit_queued_goal_at_index(0)

    assert result is False
    assert len(app._pending_messages) == 2
    assert app._chat_input.value == ""


def test_edit_queued_goal_at_index_blocked_by_pending_input() -> None:
    """Editing is blocked when the chat input has draft content."""
    app = _QueueStub()
    app._pending_messages = deque([QueuedMessage(text="goal", mode="normal")])
    app._chat_input.value = "existing draft"

    result = app.edit_queued_goal_at_index(0)

    assert result is False
    assert len(app._pending_messages) == 1


def test_submit_queued_goal_at_index_removes_correct_goal() -> None:
    """Submitting by index pops the goal and schedules it for execution."""
    app = _QueueStub()
    app._pending_messages = deque(
        [
            QueuedMessage(text="first", mode="normal"),
            QueuedMessage(text="second", mode="normal"),
            QueuedMessage(text="third", mode="normal"),
        ]
    )
    app._agent_running = False
    app._shell_running = False
    app._processing_pending = False
    app._process_message = MagicMock()

    with (
        patch.object(app, "_refresh_queued_goal_tips"),
        patch("asyncio.ensure_future"),
    ):
        result = app.submit_queued_goal_at_index(1)

    assert result is True
    remaining = list(app._pending_messages)
    assert len(remaining) == 2
    assert remaining[0].text == "first"
    assert remaining[1].text == "third"


def test_submit_queued_goal_at_index_blocked_when_busy() -> None:
    """Submitting is blocked when an agent is already running."""
    app = _QueueStub()
    app._pending_messages = deque([QueuedMessage(text="goal", mode="normal")])
    app._agent_running = True
    app._shell_running = False
    app._processing_pending = False

    result = app.submit_queued_goal_at_index(0)

    assert result is False
    assert len(app._pending_messages) == 1


def test_submit_queued_goal_at_index_out_of_range_returns_false() -> None:
    """Out-of-range index returns False without modifying the queue."""
    app = _QueueStub()
    app._pending_messages = deque([QueuedMessage(text="only", mode="normal")])
    app._agent_running = False
    app._shell_running = False
    app._processing_pending = False

    assert app.submit_queued_goal_at_index(5) is False
    assert app.submit_queued_goal_at_index(-1) is False
    assert len(app._pending_messages) == 1


def test_discard_queue_clears_pending_messages() -> None:
    """_discard_queue clears the pending queue and deferred actions."""
    app = _QueueStub()
    app._pending_messages = deque(
        [
            QueuedMessage(text="a", mode="normal"),
            QueuedMessage(text="b", mode="normal"),
        ]
    )
    app._deferred_actions = []

    app._discard_queue()

    assert len(app._pending_messages) == 0
    assert len(app._deferred_actions) == 0


# ---------------------------------------------------------------------------
# activate() visual feedback tests
# ---------------------------------------------------------------------------


def test_activate_noop_when_empty() -> None:
    """activate() is a no-op when there are no goals."""
    bar = QueuedGoalsBar()
    bar._goals = []
    bar._show_tips = False
    bar.activate()
    assert bar._show_tips is False
    assert bar._selected_index == 0


def test_activate_resets_selection_and_shows_tips() -> None:
    """activate() resets selection to 0 and enables tips."""
    bar = QueuedGoalsBar()
    goals = [
        QueuedMessage(text="first", mode="normal"),
        QueuedMessage(text="second", mode="normal"),
        QueuedMessage(text="third", mode="normal"),
    ]
    bar.set_goals(goals)
    bar.move_selection(2)  # select last
    bar._show_tips = False

    with (
        patch.object(bar, "focus"),
        patch.object(bar, "set_timer"),
    ):
        bar.activate()

    assert bar._selected_index == 0
    assert bar._show_tips is True


def test_flash_activated_adds_class() -> None:
    """_flash_activated adds the -activated class when focused."""
    bar = QueuedGoalsBar()
    bar._goals = [QueuedMessage(text="goal", mode="normal")]
    with (
        patch.object(type(bar), "has_focus", new_callable=PropertyMock, return_value=True),
        patch.object(bar, "set_timer"),
    ):
        bar._flash_activated()
    assert bar.has_class("-activated")


def test_clear_activated_removes_class() -> None:
    """_clear_activated removes the -activated class."""
    bar = QueuedGoalsBar()
    bar.add_class("-activated")
    assert bar.has_class("-activated")

    bar._clear_activated()
    assert not bar.has_class("-activated")


def test_on_focus_shows_tips_when_goals_present() -> None:
    """on_focus enables tips when the bar has goals."""
    bar = QueuedGoalsBar()
    bar._goals = [QueuedMessage(text="goal", mode="normal")]
    bar._show_tips = False

    bar.on_focus(MagicMock())

    assert bar._show_tips is True


def test_on_focus_noop_when_empty() -> None:
    """on_focus is a no-op when the bar has no goals."""
    bar = QueuedGoalsBar()
    bar._goals = []
    bar._show_tips = False

    bar.on_focus(MagicMock())

    assert bar._show_tips is False


def test_on_blur_clears_activated() -> None:
    """on_blur removes the -activated flash class."""
    bar = QueuedGoalsBar()
    bar.add_class("-activated")
    assert bar.has_class("-activated")

    bar.on_blur(MagicMock())

    assert not bar.has_class("-activated")
