"""Tests for UserMessage card styling."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages.user import QueuedUserMessage, UserMessage


def test_user_message_echoes_chat_input_surface_card() -> None:
    """UserMessage uses the same surface fill + solid border as ChatInput."""
    css = UserMessage.DEFAULT_CSS
    assert "background: $surface" in css
    assert "border: solid $primary" in css
    assert "border-left:" not in css


def test_user_message_mode_borders_use_full_box() -> None:
    """Shell and command modes swap the full border color, not a left rail only."""
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
