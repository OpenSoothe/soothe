"""Loading widget with animated spinner for agent activity."""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from textual.content import Content
from textual.widgets import Static

from soothe_cli.runtime.presentation.duration_format import format_duration
from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs

if TYPE_CHECKING:
    from textual.await_remove import AwaitRemove
    from textual.timer import Timer


class Spinner:
    """Animated spinner using charset-appropriate frames."""

    def __init__(self) -> None:
        """Initialize spinner."""
        self._position = 0

    @property
    def frames(self) -> tuple[str, ...]:
        """Get spinner frames from glyphs config."""
        return get_glyphs().spinner_frames

    def next_frame(self) -> str:
        """Get next animation frame.

        Returns:
            The next spinner character in the animation sequence.
        """
        frames = self.frames
        frame = frames[self._position]
        self._position = (self._position + 1) % len(frames)
        return frame

    def current_frame(self) -> str:
        """Get current frame without advancing.

        Returns:
            The current spinner character.
        """
        return self.frames[self._position]


class LoadingWidget(Static):
    """Animated loading indicator with status text and elapsed time.

    Displays: <spinner> Thinking...  (12s · esc to interrupt)

    Renders as a single Static so elapsed-time ticks do not relayout sibling
    widgets (which caused the spinner to flash on each second boundary).
    """

    DEFAULT_CSS = """
    LoadingWidget {
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        status: str = "Thinking",
        *,
        turn_start_mono: float | None = None,
        show_interrupt_hint: bool = True,
    ) -> None:
        """Initialize loading widget.

        Args:
            status: Initial status text to display.
            turn_start_monotonic: Start of the current query/turn (``time.monotonic()``). When
                omitted, the first mount time is used so elapsed still advances monotonically.
            show_interrupt_hint: When ``False``, omit the elapsed-time / esc hint (startup connect).
        """
        super().__init__()
        self._status = status
        self._spinner = Spinner()
        self._turn_start_mono: float | None = turn_start_mono
        self._show_interrupt_hint = show_interrupt_hint
        self._animation_timer: Timer | None = None
        self._paused = False
        self._paused_total_elapsed: int = 0

    @staticmethod
    def _format_status_line(status: str) -> str:
        return f" {status}... "

    def _format_hint_line(self, elapsed_secs: float) -> str:
        return f"({format_duration(elapsed_secs)} · esc to interrupt)"

    def _elapsed_seconds(self) -> float:
        if self._turn_start_mono is None:
            return 0.0
        return float(int(monotonic() - self._turn_start_mono))

    def _build_content(self) -> Content:
        colors = theme.get_theme_colors(self)
        status_part = Content.styled(self._format_status_line(self._status), colors.primary)
        if self._paused:
            spinner_part = Content.styled(get_glyphs().pause, "dim")
            hint_part = Content.styled(
                f" (paused at {format_duration(float(self._paused_total_elapsed))} · esc to interrupt)",
                colors.muted,
            )
        else:
            spinner_part = Content.styled(self._spinner.current_frame(), colors.primary)
            if self._show_interrupt_hint:
                hint_part = Content.styled(
                    f" {self._format_hint_line(self._elapsed_seconds())}",
                    colors.muted,
                )
            else:
                hint_part = Content("")
        return Content.assemble(spinner_part, status_part, hint_part)

    def _refresh_line(self) -> None:
        """Repaint the full status line without triggering layout."""
        self.update(self._build_content(), layout=False)

    def on_mount(self) -> None:
        """Start animation on mount."""
        now = monotonic()
        if self._turn_start_mono is None:
            self._turn_start_mono = now
        self._refresh_line()
        # Reduced from 0.1s (10fps) to 0.2s (5fps) to reduce UI thread contention
        self._animation_timer = self.set_interval(0.2, self._update_animation)

    def on_unmount(self) -> None:
        """Stop the animation timer when the widget leaves the DOM."""
        self._stop_timer()

    def remove(self) -> AwaitRemove:
        """Stop animation before delegating DOM removal to Textual.

        Returns:
            Awaitable that completes once the widget is removed from the DOM.
        """
        self._stop_timer()
        return super().remove()

    def _stop_timer(self) -> None:
        """Stop the animation timer if it is running."""
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def _update_animation(self) -> None:
        """Advance the spinner and repaint the full line."""
        if self._paused:
            return

        # Skip update if widget is not visible on screen
        if not self.is_on_screen:
            return

        self._spinner.next_frame()
        self._refresh_line()

    def set_status(self, status: str) -> None:
        """Update the status text.

        Args:
            status: New status text
        """
        self._status = status
        if self.is_mounted:
            self._refresh_line()

    def activate_status(self, status: str, *, show_interrupt_hint: bool | None = None) -> None:
        """Resume animation (if paused) and set status text."""
        self._paused = False
        self._status = status
        if show_interrupt_hint is not None:
            self._show_interrupt_hint = show_interrupt_hint
        if self.is_mounted:
            self._refresh_line()

    def set_turn_start_mono(self, turn_start: float) -> None:
        """Anchor total elapsed time to the start of the user query (if not already set)."""
        if self._turn_start_mono is None:
            self._turn_start_mono = turn_start

    def pause(self, status: str = "Awaiting decision") -> None:
        """Pause the animation and update status.

        Args:
            status: Status to show while paused
        """
        self._paused = True
        now = monotonic()
        if self._turn_start_mono is not None:
            self._paused_total_elapsed = int(now - self._turn_start_mono)
        self._status = status
        if self.is_mounted:
            self._refresh_line()

    def resume(self) -> None:
        """Resume the animation."""
        self._paused = False
        self._status = "Thinking"
        if self.is_mounted:
            self._refresh_line()

    def stop(self) -> None:
        """Stop the animation (widget will be removed by caller)."""
        self._stop_timer()
