"""Tests for ``soothe.skills.catalog`` and slash helpers."""

from __future__ import annotations

from pathlib import Path

from soothe.config import SootheConfig
from soothe.skills.catalog import (
    build_skill_invocation_envelope,
    resolve_skill_directory,
    wire_entries_for_agent_config,
)
from soothe.ux.tui.command_registry import build_skill_commands_from_wire


def test_wire_entries_sorted_and_pathless(tmp_path: Path) -> None:
    d = tmp_path / "alpha-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: alpha-skill\ndescription: A\ntest: x\n---\n# Hi\n",
        encoding="utf-8",
    )
    cfg = SootheConfig()
    cfg.skills = [str(d)]
    rows = wire_entries_for_agent_config(cfg)
    assert rows
    names = [r["name"] for r in rows]
    assert names == sorted(names, key=str.lower)
    assert any(r["name"] == "alpha-skill" for r in rows)
    for r in rows:
        assert "path" not in r


def test_resolve_skill_directory_last_wins(tmp_path: Path) -> None:
    first = tmp_path / "one"
    first.mkdir()
    (first / "SKILL.md").write_text(
        "---\nname: dupname\ndescription: first\n---\nbody1",
        encoding="utf-8",
    )
    second = tmp_path / "two"
    second.mkdir()
    (second / "SKILL.md").write_text(
        "---\nname: dupname\ndescription: second\n---\nbody2",
        encoding="utf-8",
    )
    cfg = SootheConfig()
    cfg.skills = [str(first), str(second)]
    meta = resolve_skill_directory(cfg, "dupname")
    assert meta is not None
    assert meta["description"] == "second"


def test_build_skill_invocation_envelope_includes_name() -> None:
    meta = {
        "name": "x",
        "description": "d",
        "path": "/tmp/ignored",
        "source": "test",
    }
    env = build_skill_invocation_envelope(meta, "---\nname: x\n---\nDo thing.\n", "please")
    assert "x" in env.prompt
    assert "Do thing" in env.prompt
    assert env.message_kwargs is not None
    assert env.message_kwargs["additional_kwargs"]["soothe_skill"] == "x"


def test_build_skill_commands_from_wire_filters_aliases() -> None:
    rows = [
        {"name": "remember", "description": "R"},
        {"name": "my-skill", "description": "M"},
    ]
    out = build_skill_commands_from_wire(rows)
    names = [t[0] for t in out]
    assert "/skill:remember" not in names
    assert any(n == "/skill:my-skill" for n in names)
