"""User message widgets."""

from __future__ import annotations

from typing import Any

from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import (
    MODE_DISPLAY_GLYPHS,
    PREFIX_TO_MODE,
    is_ascii_mode,
)
from soothe_cli.tui.input import EMAIL_PREFIX_PATTERN, INPUT_HIGHLIGHT_PATTERN
from soothe_cli.tui.widgets.messages._helpers import _mode_color


class UserMessage(Static):
    """Widget displaying a user message with enhanced styling."""

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0;
        background: $surface;
        border: solid $primary;
    }

    UserMessage.-mode-shell {
        border: solid $mode-bash;
    }

    UserMessage.-mode-command {
        border: solid $mode-command;
    }

    UserMessage:hover {
        border: solid $primary-lighten-1;
    }

    UserMessage.-mode-shell:hover {
        border: solid $mode-bash;
    }

    UserMessage.-mode-command:hover {
        border: solid $mode-command;
    }
    """
    """Surface card with full border echoing ChatInput so submitted prompts stand out in the flow."""

    def __init__(self, content: str, **kwargs: Any) -> None:
        """Initialize a user message.

        Args:
            content: The message content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content

    def on_mount(self) -> None:
        """Add CSS classes for mode-specific border and ASCII border type."""
        mode = PREFIX_TO_MODE.get(self._content[:1]) if self._content else None
        if mode:
            self.add_class(f"-mode-{mode}")
        if is_ascii_mode():
            self.add_class("-ascii")

    def render(self) -> Content:
        """Render the styled user message with role indicator.

        Returns:
            Styled Content with role header, mode prefix, and highlighted mentions.
        """
        colors = theme.get_theme_colors(self)
        parts: list[str | tuple[str, str]] = []
        content = self._content

        # Add role indicator header
        parts.append(("> ", f"bold {colors.primary}"))

        # Use mode-specific prefix indicator when content starts with a
        # mode trigger character (e.g. "!" for shell, "/" for commands).
        # The display glyph may differ from the trigger (e.g. "$" for shell).
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            parts.append((f"{glyph} ", f"bold {_mode_color(mode, self)}"))
            content = content[1:]

        # Highlight @mentions and /commands in the content
        last_end = 0
        for match in INPUT_HIGHLIGHT_PATTERN.finditer(content):
            start, end = match.span()
            token = match.group()

            # Skip @mentions that look like email addresses
            if token.startswith("@") and start > 0:
                char_before = content[start - 1]
                if EMAIL_PREFIX_PATTERN.match(char_before):
                    continue

            # Add text before the match (high-contrast body)
            if start > last_end:
                parts.append((content[last_end:start], colors.foreground))

            # The regex only matches tokens starting with / or @
            if token.startswith("/") and start == 0:
                # /command at start
                parts.append((token, f"bold {colors.warning}"))
            elif token.startswith("@"):
                # @file mention
                parts.append((token, f"bold {colors.primary}"))
            last_end = end

        # Add remaining text after last match
        if last_end < len(content):
            parts.append((content[last_end:], colors.foreground))

        return Content.assemble(*parts)


class QueuedUserMessage(Static):
    """Widget displaying a queued (pending) user message in grey.

    This is an ephemeral widget that gets removed when the message is dequeued.
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    QueuedUserMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: $surface-darken-1;
        border: solid $panel;
    }
    """
    """Muted ChatInput echo for pending messages; text uses terminal `dim` style."""

    def __init__(self, content: str, **kwargs: Any) -> None:
        """Initialize a queued user message.

        Args:
            content: The message content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content

    def on_mount(self) -> None:
        """Add ASCII border class when in ASCII mode."""
        if is_ascii_mode():
            self.add_class("-ascii")

    def render(self) -> Content:
        """Render the queued user message (greyed out).

        Returns:
            Styled Content with dimmed prefix and body matching the welcome banner.
        """
        content = self._content
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            prefix = (f"{glyph} ", "dim")
            content = content[1:]
        else:
            prefix = ("> ", "dim")
        return Content.assemble(prefix, (content, "dim"))
