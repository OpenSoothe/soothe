"""Tests for ``soothe_cli.tui.command_registry`` skill-related functions."""

from __future__ import annotations

from soothe_cli.tui.command_registry import build_skill_commands_from_wire


def test_build_skill_commands_from_wire_filters_aliases() -> None:
    rows = [
        {"name": "remember", "description": "R"},
        {"name": "my-skill", "description": "M"},
    ]
    out = build_skill_commands_from_wire(rows)
    names = [t[0] for t in out]
    assert "/skill:remember" not in names
    assert any(n == "/skill:my-skill" for n in names)
