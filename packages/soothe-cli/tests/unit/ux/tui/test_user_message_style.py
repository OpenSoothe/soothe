"""Tests for UserMessage card styling."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages.user import QueuedUserMessage, UserMessage


def test_user_message_echoes_chat_input_surface_card() -> None:
    """UserMessage uses the same surface fill + solid border as ChatInput."""
    css = UserMessage.DEFAULT_CSS
    assert "background: $surface" in css
    assert "border: solid $primary" in css
    assert "border-left:" not in css


def test_user_message_mode_borders_use_full_box() -> None:
    """Shell and command modes swap the full border color."""
    css = UserMessage.DEFAULT_CSS
    assert "UserMessage.-mode-shell" in css
    assert "border: solid $mode-bash" in css
    assert "UserMessage.-mode-command" in css
    assert "border: solid $mode-command" in css


def test_queued_user_message_is_muted_surface_card() -> None:
    """Queued messages stay visually related but dimmer than sent user cards."""
    css = QueuedUserMessage.DEFAULT_CSS
    assert "background: $surface-darken-1" in css
    assert "border: solid $panel" in css


def _render_user_message(content: str) -> tuple[object, theme.ThemeColors]:
    """Render a `UserMessage` with a fixed dark palette (no live app)."""
    colors = theme.DARK_COLORS
    widget = UserMessage(content)
    with (
        patch.object(type(widget), "app", new_callable=PropertyMock) as mock_app,
        patch("soothe_cli.tui.theme.get_theme_colors", return_value=colors),
    ):
        mock_app.return_value = MagicMock()
        return widget.render(), colors


def test_user_message_highlights_command_token_after_mode_glyph() -> None:
    """Submitted `/skill:foo args` paints the token, not just the glyph."""
    content, colors = _render_user_message("/skill:diagnose-soothe run now")
    plain = content.plain
    assert plain.startswith("> / skill:diagnose-soothe")
    command_style = f"bold {colors.mode_command}"
    styled = [(span.start, span.end, span.style) for span in content.spans]
    assert any(
        plain[start:end] == "skill:diagnose-soothe" and style == command_style
        for start, end, style in styled
    )


def test_user_message_highlights_file_mention() -> None:
    """@file mentions stay primary-accented in the body."""
    content, colors = _render_user_message("see @README.md please")
    plain = content.plain
    mention_style = f"bold {colors.primary}"
    styled = [(span.start, span.end, span.style) for span in content.spans]
    assert any(
        plain[start:end] == "@README.md" and style == mention_style for start, end, style in styled
    )
