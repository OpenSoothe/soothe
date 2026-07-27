"""Diff message widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import is_ascii_mode
from soothe_cli.tui.preview_limits import APPROVAL_DIFF_MAX_LINES
from soothe_cli.tui.widgets.diff import compose_diff_lines

if TYPE_CHECKING:
    from textual.app import ComposeResult


class DiffMessage(Static):
    """Widget displaying a diff with syntax highlighting."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    DiffMessage {
        height: auto;
        padding: 0 2;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $primary;
    }

    DiffMessage .diff-header {
        text-style: bold;
        margin: 0;
    }
    """
    """Diff syntax coloring per theme: additions, removals, muted context."""

    def __init__(
        self,
        diff_content: str,
        file_path: str = "",
        *,
        action_label: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a diff message.

        Args:
            diff_content: The unified diff content
            file_path: Path to the file being modified
            action_label: Short verb for the change (e.g. ``Edited``, ``Deleted``)
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._diff_content = diff_content
        self._file_path = file_path
        self._action_label = action_label.strip()

    def compose(self) -> ComposeResult:
        """Compose the diff message layout.

        Yields:
            Widgets displaying the diff header and formatted content.
        """
        if self._file_path:
            if self._action_label:
                yield Static(
                    Content.from_markup(
                        "[bold]$action:[/bold] $path",
                        action=self._action_label,
                        path=self._file_path,
                    ),
                    classes="diff-header",
                )
            else:
                yield Static(
                    Content.from_markup("[bold]File: $path[/bold]", path=self._file_path),
                    classes="diff-header",
                )

        # Render the diff with per-line Statics (CSS-driven backgrounds)
        yield from compose_diff_lines(self._diff_content, max_lines=APPROVAL_DIFF_MAX_LINES)

    def on_mount(self) -> None:
        """Set border style based on charset mode."""
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
