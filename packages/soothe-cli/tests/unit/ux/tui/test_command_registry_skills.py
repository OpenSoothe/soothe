"""Tests for ``soothe_cli.tui.command_registry`` skill-related functions."""

from __future__ import annotations

from soothe_cli.tui.command_registry import build_skill_commands_from_wire


def test_build_skill_commands_from_wire_includes_all_skills() -> None:
    rows = [
        {"name": "weather", "description": "W"},
        {"name": "my-skill", "description": "M"},
    ]
    out = build_skill_commands_from_wire(rows)
    names = [t[0] for t in out]
    assert "/skill:weather" in names
    assert "/skill:my-skill" in names
