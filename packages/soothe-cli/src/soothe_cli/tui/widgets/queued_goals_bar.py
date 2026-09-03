"""Queued goals bar widget — shows pending queued goals above the chat input.

A docked bar (modeled on ``PinnedGoalBar``) that renders all queued goals as
selectable rows.  Each row shows the goal text in a muted style.  The bar is
hidden when the queue is empty and visible when goals are pending.

Interactions:
    - Enter:   submit the selected queued goal for immediate execution.
    - Up:      edit the selected queued goal (moves it to the chat input).
    - Down:    navigate selection down.
    - Esc:     cancel the selected queued goal.

The bar is fed by the app's ``_refresh_queued_goal_tips`` →
``_sync_queued_goals_bar`` pipeline, which pushes a snapshot of
``_pending_messages`` via ``set_goals()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.content import Content
from textual.widgets import Static

from soothe_cli.display import theme
from soothe_cli.settings import (
    MODE_DISPLAY_GLYPHS,
    PREFIX_TO_MODE,
    is_ascii_mode,
)
from soothe_cli.tui.input import EMAIL_PREFIX_PATTERN, FILE_MENTION_PATTERN, command_token_span
from soothe_cli.tui.widgets.messages._helpers import _mode_color

if TYPE_CHECKING:
    from textual.events import Key

    from soothe_cli.tui.app._types import QueuedMessage

_QUEUE_TIPS_ASCII = "  ·  enter submit | up edit | esc cancel"
_QUEUE_TIPS_UNICODE = "  ·  enter submit · up edit · esc cancel"
_MAX_WIDTH_FALLBACK = 80
"""Fallback terminal width when the app hasn't measured the viewport yet."""


class QueuedGoalsBar(Static):
    """A docked bar that shows all queued goals as selectable rows.

    The bar receives the current queue snapshot via ``set_goals()`` and
    re-renders all rows.  A selection cursor tracks which row the user
    is focused on for keyboard-driven edit/cancel.
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    can_focus = True
    """Allow the bar to receive keyboard focus so on_key fires for
    Up/Down/Enter/Esc navigation."""

    DEFAULT_CSS = """
    QueuedGoalsBar {
        height: auto;
        min-height: 0;
        padding: 0 1;
        background: $surface-darken-1;
        border-top: solid $primary;
        color: $text-muted;
        transition: background 200ms, border-top 200ms, color 200ms;
    }

    QueuedGoalsBar:focus {
        background: $boost;
        border-top: double $accent;
        color: $text;
        text-style: bold;
    }

    QueuedGoalsBar.-ascii {
        border-top: ascii $primary;
    }

    QueuedGoalsBar.-ascii:focus {
        border-top: ascii $accent;
    }

    QueuedGoalsBar.-activated {
        background: $accent 30%;
    }
    """
    """Compact docked bar listing all queued goals."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the queued goals bar."""
        super().__init__(**kwargs)
        self._goals: list[QueuedMessage] = []
        self._selected_index: int = 0
        self._show_tips: bool = False

    def on_mount(self) -> None:
        """Add ASCII border class when in ASCII mode."""
        if is_ascii_mode():
            self.add_class("-ascii")

    def on_focus(self, event: Any) -> None:
        """Visual activation when the bar receives keyboard focus.

        Ensures tips are visible so the user knows the available actions.
        """
        if not self._goals:
            return
        self._show_tips = True
        self.refresh(layout=False)

    def on_blur(self, event: Any) -> None:
        """Clean up visual state when the bar loses focus."""
        self._clear_activated()

    def _clear_activated(self) -> None:
        """Remove the activation flash class."""
        self.remove_class("-activated")

    def activate(self) -> None:
        """Public entry point for the Ctrl+q action.

        Ensures the bar is visible, resets selection to the head of the
        queue, shows interaction tips, triggers a brief background flash,
        and moves keyboard focus to the bar so arrow-key navigation is
        immediately available.
        """
        if not self._goals:
            return
        self._selected_index = 0
        self._show_tips = True
        self.refresh(layout=False)
        self.focus()
        # Brief background flash for visual activation feedback.
        # Scheduled slightly after the focus refresh so the class
        # transition is visible to the user.
        self.set_timer(0.01, self._flash_activated)

    def _flash_activated(self) -> None:
        """Add the activation flash class and schedule its removal."""
        if not self.has_focus or not self._goals:
            return
        self.add_class("-activated")
        self.set_timer(0.4, self._clear_activated)

    def set_goals(self, goals: list[QueuedMessage]) -> None:
        """Replace the bar's goal list and re-render.

        Args:
            goals: The current queue snapshot (list of ``QueuedMessage``).
        """
        self._goals = list(goals)
        # Clamp selection into valid range
        if self._selected_index >= len(self._goals):
            self._selected_index = max(0, len(self._goals) - 1)
        # Update visibility: show when non-empty, hide when empty
        self.styles.display = "block" if self._goals else "none"
        # layout=True so the parent container re-measures our height: auto
        # and all rows become visible (plain refresh() only repaints pixels).
        self.refresh(layout=True)

    @property
    def has_goals(self) -> bool:
        """Return whether the bar has any queued goals."""
        return bool(self._goals)

    def set_show_tips(self, show: bool) -> None:
        """Toggle whether queue interaction tips are rendered.

        Args:
            show: Whether to show the tips suffix.
        """
        if self._show_tips == show:
            return
        self._show_tips = show
        self.refresh(layout=False)

    def move_selection(self, delta: int) -> bool:
        """Move the selection cursor by ``delta`` (clamped).

        Args:
            delta: Positive = down, negative = up.

        Returns:
            ``True`` if the selection changed.
        """
        if not self._goals:
            return False
        new_index = self._selected_index + delta
        new_index = max(0, min(new_index, len(self._goals) - 1))
        if new_index == self._selected_index:
            return False
        self._selected_index = new_index
        self.refresh(layout=False)
        return True

    def get_selected_index(self) -> int:
        """Return the current selection index (0-based)."""
        return self._selected_index

    def select_and_edit(self) -> bool:
        """Open the editor on the selected queued goal.

        Delegates to the app's ``edit_queued_goal_at_index`` method.

        Returns:
            ``True`` if the edit was initiated.
        """
        if not self._goals:
            return False
        index = self._selected_index
        handler = getattr(self.app, "edit_queued_goal_at_index", None)
        if callable(handler):
            try:
                return bool(handler(index))
            except Exception:  # noqa: BLE001
                return False
        return False

    def submit_selected(self) -> bool:
        """Submit the selected queued goal for immediate execution.

        Delegates to the app's ``submit_queued_goal_at_index`` method.

        Returns:
            ``True`` if the submission was initiated.
        """
        if not self._goals:
            return False
        index = self._selected_index
        handler = getattr(self.app, "submit_queued_goal_at_index", None)
        if callable(handler):
            try:
                return bool(handler(index))
            except Exception:  # noqa: BLE001
                return False
        return False

    def cancel_selected(self) -> bool:
        """Cancel the selected queued goal.

        Delegates to the app's ``cancel_queued_goal_at_index`` method.

        Returns:
            ``True`` if the cancel was initiated.
        """
        if not self._goals:
            return False
        index = self._selected_index
        handler = getattr(self.app, "cancel_queued_goal_at_index", None)
        if callable(handler):
            try:
                return bool(handler(index))
            except Exception:  # noqa: BLE001
                return False
        return False

    def on_key(self, event: Key) -> None:
        """Handle keyboard navigation when the bar is focused.

        Args:
            event: The key event.
        """
        if not self._goals:
            return
        if event.key == "up":
            # Up edits the selected goal (moves it to the chat input).
            if self.select_and_edit():
                event.prevent_default()
                event.stop()
        elif event.key == "down":
            if self.move_selection(1):
                event.prevent_default()
                event.stop()
        elif event.key == "enter":
            # Enter submits the selected goal for immediate execution.
            if self.submit_selected():
                event.prevent_default()
                event.stop()
        elif event.key == "escape":
            if self.cancel_selected():
                event.prevent_default()
                event.stop()

    def render(self) -> Content:
        """Render all queued goals as selectable rows.

        Each row is individually truncated to the available width so that a
        long first goal doesn't hide subsequent goals.  Returns a styled
        ``Content`` with one row per queued goal, the selected row
        highlighted, and an optional tips suffix on the last row.
        """
        if not self._goals:
            return Content("")

        colors = theme.get_theme_colors(self)
        available_width = self._available_width()
        row_parts: list[str | tuple[str, str]] = []

        for i, goal in enumerate(self._goals):
            is_selected = i == self._selected_index
            is_last = i == len(self._goals) - 1

            # Build this row's styled segments, then truncate the row
            # individually so a long row doesn't swallow later goals.
            parts: list[str | tuple[str, str]] = []

            # Row prefix: ">" for selected, " " for others
            prefix_glyph = ">" if is_selected else " "
            prefix_style = f"bold {colors.primary}" if is_selected else "dim"
            parts.append((f"{prefix_glyph} ", prefix_style))

            # Render the goal text with mode glyph and mention highlighting
            content = goal.text
            mode = PREFIX_TO_MODE.get(content[:1]) if content else None
            if mode:
                glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
                mode_style = f"bold {_mode_color(mode, self)}" if is_selected else "dim"
                parts.append((f"{glyph} ", mode_style))
                content = content[1:]

            text_style = colors.foreground if is_selected else "dim"

            # Highlight leading command token and @file mentions
            last_end = 0
            if mode == "command":
                start, end = command_token_span(content)
                if end > start:
                    cmd_style = f"bold {colors.mode_command}" if is_selected else "dim"
                    parts.append((content[start:end], cmd_style))
                    last_end = end

            for match in FILE_MENTION_PATTERN.finditer(content):
                start, end = match.span()
                if start < last_end:
                    continue
                token = match.group()

                if start > 0:
                    char_before = content[start - 1]
                    if EMAIL_PREFIX_PATTERN.match(char_before):
                        continue

                if start > last_end:
                    parts.append((content[last_end:start], text_style))

                mention_style = f"bold {colors.primary}" if is_selected else "dim"
                parts.append((token, mention_style))
                last_end = end

            if last_end < len(content):
                parts.append((content[last_end:], text_style))

            # Tips on the last row
            if is_last and self._show_tips:
                tips_text = _QUEUE_TIPS_ASCII if is_ascii_mode() else _QUEUE_TIPS_UNICODE
                parts.append((tips_text, f"dim {colors.warning}"))

            # Truncate this row individually, then append to the bar.
            row = Content.assemble(*parts).truncate(available_width, ellipsis=True)
            row_parts.append(row)

            # Newline between rows (not after the last)
            if not is_last:
                row_parts.append("\n")

        return Content.assemble(*row_parts)

    def _available_width(self) -> int:
        """Return the available terminal width for the bar content.

        Accounts for the padding (0 1 = 2 columns).

        Returns:
            Column count available for text content.
        """
        try:
            size = self.size
            width = size.width if size.width > 0 else _MAX_WIDTH_FALLBACK
        except Exception:  # noqa: BLE001
            width = _MAX_WIDTH_FALLBACK
        return max(width - 2, 10)
