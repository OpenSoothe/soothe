"""Tests for the TUI help modal content."""

from __future__ import annotations

from soothe_cli.tui.command_registry import COMMANDS
from soothe_cli.tui.widgets.help_screen import (
    build_command_rows,
    build_help_content,
    build_keyboard_shortcut_rows,
)


def test_build_command_rows_includes_registry_and_extras() -> None:
    """Help lists every registered slash command plus dynamic skill/subagent hints."""
    rows = build_command_rows()
    labels = {label for label, _ in rows}
    for cmd in COMMANDS:
        if cmd.aliases:
            assert f"{cmd.name} ({', '.join(cmd.aliases)})" in labels
        else:
            assert cmd.name in labels
    assert "/skill:<name>" in labels
    assert "/«subagent»" in labels


def test_build_keyboard_shortcut_rows_cover_core_bindings() -> None:
    """Help documents the primary chat and app shortcuts."""
    rows = dict(build_keyboard_shortcut_rows())
    assert rows["Enter"] == "Submit message"
    assert rows["Ctrl+D"] == "Type exit, quit, or /quit to exit the TUI"
    assert rows["Ctrl+C"] == "Clear input or interrupt running agent/shell"
    assert rows["Ctrl+T"] == "Toggle plan panel above thinking row"
    assert rows["Shift+Tab"] == "Toggle clarification relay mode (Auto/Manual)"


def test_build_help_content_includes_docs_link() -> None:
    """Help body ends with a documentation link."""
    content = build_help_content()
    plain = str(content)
    assert "Slash Commands" in plain
    assert "Keyboard Shortcuts" in plain
    assert "Documentation:" in plain
    assert "github.com/mirasoth/soothe/docs" in plain
