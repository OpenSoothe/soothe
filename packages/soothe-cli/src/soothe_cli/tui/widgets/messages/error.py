"""Error message widget."""

from __future__ import annotations

from typing import Any

from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header


class ErrorMessage(Static):
    """Widget displaying an error message."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    ErrorMessage {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: $error-muted;
        color: white;
    }
    """
    """Tinted background to visually separate errors from output."""

    def __init__(self, error: str, **kwargs: Any) -> None:
        """Initialize an error message.

        Args:
            error: The error message
            **kwargs: Additional arguments passed to parent
        """
        # Store raw content for serialization
        self._content = error
        super().__init__(**kwargs)

    def render(self) -> Content:
        """Render with theme-aware colors.

        Returns:
            Styled error content with theme-appropriate color.
        """
        colors = theme.get_theme_colors(self)
        return Content.assemble(
            _assemble_card_header(
                self,
                "",
                status="error",
                accent=colors.error,
            ),
            Content.styled("Error: ", f"bold {colors.error}"),
            self._content,
        )
