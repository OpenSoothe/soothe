"""Tests for ``soothe_cli.tui.command_registry`` skill-related functions."""

from __future__ import annotations

from soothe_cli.tui.command_registry import build_skill_commands_from_wire, parse_skill_command


def test_build_skill_commands_from_wire_includes_all_skills() -> None:
    rows = [
        {"name": "weather", "description": "W"},
        {"name": "my-skill", "description": "M"},
    ]
    out = build_skill_commands_from_wire(rows)
    names = [t[0] for t in out]
    assert "/skill:weather" in names
    assert "/skill:my-skill" in names


class TestParseSkillCommand:
    def test_skill_prefix_with_name_and_args(self) -> None:
        name, args = parse_skill_command("/skill:weather shanghai tomorrow")
        assert name == "weather"
        assert args == "shanghai tomorrow"

    def test_skills_prefix_with_name_and_args(self) -> None:
        name, args = parse_skill_command("/skills:weather shanghai tomorrow")
        assert name == "weather"
        assert args == "shanghai tomorrow"

    def test_skill_prefix_name_only(self) -> None:
        name, args = parse_skill_command("/skill:weather")
        assert name == "weather"
        assert args == ""

    def test_skills_prefix_name_only(self) -> None:
        name, args = parse_skill_command("/skills:weather")
        assert name == "weather"
        assert args == ""

    def test_bare_skill_prefix(self) -> None:
        name, args = parse_skill_command("/skill:")
        assert name == ""
        assert args == ""

    def test_bare_skills_prefix(self) -> None:
        name, args = parse_skill_command("/skills:")
        assert name == ""
        assert args == ""

    def test_name_normalized_to_lowercase(self) -> None:
        name, args = parse_skill_command("/skill:MySkill")
        assert name == "myskill"
