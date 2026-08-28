"""Pinned goal bar widget — keeps the latest user message visible at the top."""

from __future__ import annotations

from typing import Any

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

_MAX_WIDTH_FALLBACK = 80
"""Fallback terminal width when the app hasn't measured the viewport yet."""


class PinnedGoalBar(Static):
    """A docked bar that pins the latest user message at the top of the screen.

    Renders a compact, single-line view of the most recent user query/goal
    using the same visual cues as `UserMessage` (the `> ` prefix, mode glyphs,
    `@file` mentions). Long messages are truncated with an ellipsis so the
    bar never occupies more than one terminal row.

    Visibility is controlled by scroll position via `set_visible()`: the bar
    appears when the user scrolls away from the bottom of the chat (so the
    latest message is no longer in view), and hides when they scroll back.
    A user can manually override with `toggle_user_override()` (Ctrl+g) to
    force-hide the bar even while scrolled up.
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    PinnedGoalBar {
        height: auto;
        min-height: 0;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    PinnedGoalBar.-ascii {
        border-bottom: ascii $primary;
    }
    """
    """Compact docked bar echoing the latest user message."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the pinned goal bar.

        Args:
        **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
        self._content: str = ""
        self._user_override: bool = False
        """When True, the user explicitly hid the bar; scroll-driven visibility is skipped."""

    def on_mount(self) -> None:
        """Add ASCII border class when in ASCII mode."""
        if is_ascii_mode():
            self.add_class("-ascii")

    def set_message(self, text: str) -> None:
        """Store the latest user message content and re-render.

        This does NOT change visibility — call `set_visible()` to show/hide
        the bar based on scroll position.

        Args:
        text: The user message content to pin.
        """
        self._content = text
        self.refresh()

    def set_visible(self, visible: bool) -> None:
        """Show or hide the bar based on scroll position.

        Respects the user override flag: if the user explicitly hid the bar
        via Ctrl+g, this is a no-op. If no content has been set yet, the bar
        stays hidden regardless.

        Args:
        visible: Whether the chat is scrolled away from the bottom.
        """
        if self._user_override or not self._content:
            return
        self.styles.display = "block" if visible else "none"

    def toggle_user_override(self) -> bool:
        """Toggle the user override flag.

        When enabling the override, the bar is hidden immediately. When
        disabling, the bar resumes scroll-driven visibility (the caller
        should re-evaluate scroll position and call `set_visible`).

        Returns:
        The new override state: `True` if the bar is now force-hidden.
        """
        self._user_override = not self._user_override
        if self._user_override:
            self.styles.display = "none"
        return self._user_override

    def render(self) -> Content:
        """Render the pinned user message in compact form.

        Returns:
        Styled `Content` with role indicator, mode prefix, highlighted
        mentions, and ellipsis truncation for long messages.
        """
        if not self._content:
            return Content("")

        colors = theme.get_theme_colors(self)
        content = self._content

        parts: list[str | tuple[str, str]] = []
        parts.append(("> ", f"bold {colors.primary}"))

        # Mode-specific prefix glyph (same logic as UserMessage.render).
        mode = PREFIX_TO_MODE.get(content[:1]) if content else None
        if mode:
            glyph = MODE_DISPLAY_GLYPHS.get(mode, content[0])
            parts.append((f"{glyph} ", f"bold {_mode_color(mode, self)}"))
            content = content[1:]

        # Highlight leading command token and @file mentions.
        last_end = 0
        if mode == "command":
            start, end = command_token_span(content)
            if end > start:
                parts.append((content[start:end], f"bold {colors.mode_command}"))
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
                parts.append((content[last_end:start], colors.foreground))

            parts.append((token, f"bold {colors.primary}"))
            last_end = end

        if last_end < len(content):
            parts.append((content[last_end:], colors.foreground))

        assembled = Content.assemble(*parts)
        return assembled.truncate(self._available_width(), ellipsis=True)

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
