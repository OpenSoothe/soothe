"""Loading widget with animated spinner for agent activity."""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.formatting import format_duration

if TYPE_CHECKING:
    from textual.app import ComposeResult
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

    The elapsed value updates at most once per second so the line does not flicker.
    """

    DEFAULT_CSS = """
    LoadingWidget {
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }

    LoadingWidget .loading-container {
        height: auto;
        width: 100%;
    }

    LoadingWidget .loading-spinner {
        width: auto;
        color: $primary;
    }

    LoadingWidget .loading-status {
        width: auto;
        color: $primary;
    }

    LoadingWidget .loading-hint {
        width: auto;
        color: $text-muted;
        margin-left: 1;
    }
    """

    def __init__(self, status: str = "Thinking", *, turn_start_mono: float | None = None) -> None:
        """Initialize loading widget.

        Args:
            status: Initial status text to display.
            turn_start_monotonic: Start of the current query/turn (``time.monotonic()``). When
                omitted, the first mount time is used so elapsed still advances monotonically.
        """
        super().__init__()
        self._status = status
        self._spinner = Spinner()
        self._turn_start_mono: float | None = turn_start_mono
        self._spinner_widget: Static | None = None
        self._status_widget: Static | None = None
        self._hint_widget: Static | None = None
        self._animation_timer: Timer | None = None
        self._paused = False
        self._paused_total_elapsed: int = 0
        self._last_hint_elapsed_int: int = -1

    def compose(self) -> ComposeResult:
        """Compose the loading widget layout.

        Yields:
            Widgets for spinner, status text, and hint.
        """
        with Horizontal(classes="loading-container"):
            self._spinner_widget = Static(self._spinner.current_frame(), classes="loading-spinner")
            yield self._spinner_widget

            self._status_widget = Static(
                self._format_status_line(self._status), classes="loading-status"
            )
            yield self._status_widget

            self._hint_widget = Static(self._format_hint_line(0.0), classes="loading-hint")
            yield self._hint_widget

    @staticmethod
    def _format_status_line(status: str) -> str:
        return f" {status}... "

    def _format_hint_line(self, elapsed_secs: float) -> str:
        return f"({format_duration(elapsed_secs)} · esc to interrupt)"

    def on_mount(self) -> None:
        """Start animation on mount."""
        now = monotonic()
        if self._turn_start_mono is None:
            self._turn_start_mono = now
        self._animation_timer = self.set_interval(0.1, self._update_animation)

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
        """Update spinner and elapsed time."""
        if self._paused:
            return

        if self._spinner_widget:
            frame = self._spinner.next_frame()
            self._spinner_widget.update(frame)

        if self._hint_widget and self._turn_start_mono is not None:
            now = monotonic()
            total_s = now - self._turn_start_mono
            elapsed_int = int(total_s)
            if elapsed_int != self._last_hint_elapsed_int:
                self._last_hint_elapsed_int = elapsed_int
                self._hint_widget.update(self._format_hint_line(float(elapsed_int)))

    def set_status(self, status: str) -> None:
        """Update the status text.

        Args:
            status: New status text
        """
        self._status = status
        if self._status_widget:
            self._status_widget.update(self._format_status_line(status))

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
        if self._status_widget:
            self._status_widget.update(self._format_status_line(status))
        if self._hint_widget:
            self._hint_widget.update(
                f"(paused at {format_duration(float(self._paused_total_elapsed))} · esc to interrupt)"
            )
        if self._spinner_widget:
            self._spinner_widget.update(Content.styled(get_glyphs().pause, "dim"))

    def resume(self) -> None:
        """Resume the animation."""
        self._paused = False
        self._status = "Thinking"
        now = monotonic()
        if self._status_widget:
            self._status_widget.update(self._format_status_line(self._status))
        if self._hint_widget and self._turn_start_mono is not None:
            elapsed_int = int(now - self._turn_start_mono)
            self._last_hint_elapsed_int = elapsed_int
            self._hint_widget.update(self._format_hint_line(float(elapsed_int)))

    def stop(self) -> None:
        """Stop the animation (widget will be removed by caller)."""
        self._stop_timer()
