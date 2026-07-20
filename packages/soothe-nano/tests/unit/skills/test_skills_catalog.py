"""Tests for ``soothe.skills.catalog``."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config import SootheConfig
from soothe_nano.skills.catalog import (
    _parse_frontmatter,
    build_skill_invocation_envelope,
    format_slash_skill_invoke_line,
    parse_slash_skill_user_line,
    resolve_skill_directory,
    try_expand_slash_skill_user_line,
    wire_entries_for_agent_config,
)


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
    assert "Skill folder: /tmp/ignored" in env.skill_context
    assert "x" in env.prompt
    assert "Do thing" in env.prompt
    assert env.message_kwargs is not None
    assert env.message_kwargs["additional_kwargs"]["soothe_skill"] == "x"


def test_format_slash_skill_invoke_line() -> None:
    assert (
        format_slash_skill_invoke_line("weather", "what is rain") == "/skill:weather what is rain"
    )
    assert format_slash_skill_invoke_line("remember", "") == "/skill:remember"
    assert format_slash_skill_invoke_line("remember", "   ") == "/skill:remember"


def test_parse_slash_skill_user_line() -> None:
    assert parse_slash_skill_user_line("/skill:Weather please") == ("weather", "please")
    assert parse_slash_skill_user_line("  /SKILL:alpha  ") == ("alpha", "")
    assert parse_slash_skill_user_line("/skill:beta") == ("beta", "")
    assert parse_slash_skill_user_line("not a skill") is None


def test_try_expand_slash_skill_user_line(tmp_path: Path) -> None:
    d = tmp_path / "expand-me"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: expand-me\ndescription: D\n---\n# Do the thing\n",
        encoding="utf-8",
    )
    cfg = SootheConfig()
    cfg.skills = [str(d)]
    env = try_expand_slash_skill_user_line("/skill:expand-me run it", cfg)
    assert env is not None
    assert "expand-me" in env.prompt
    assert "Do the thing" in env.prompt
    assert "run it" in env.prompt
    assert env.prompt.index("User instruction") < env.prompt.index("Skill reference")
    assert "Skill: expand-me" in env.skill_context
    assert f"Skill folder: {d.resolve()}" in env.skill_context
    assert "Do the thing" in env.skill_context
    assert "User instruction" not in env.skill_context
    assert "run it" not in env.skill_context
    assert try_expand_slash_skill_user_line("/skill:missing-skill x", cfg) is None


class TestFrontmatterPathsAndWhenToUse:
    def test_paths_block_list(self) -> None:
        content = "---\nname: py-skill\ndescription: d\npaths:\n  - '*.py'\n  - '*.pyx'\n---\nbody"
        fm = _parse_frontmatter(content)
        assert fm.get("paths") == ["*.py", "*.pyx"]

    def test_when_to_use_block_scalar(self) -> None:
        content = "---\nname: x\ndescription: d\nwhen_to_use: |\n  Use for Python.\n  And also Jupyter.\n---\nbody"
        fm = _parse_frontmatter(content)
        assert "Python" in fm.get("when_to_use", "")

    def test_no_paths_no_when_to_use(self) -> None:
        content = "---\nname: plain\ndescription: d\n---\nbody"
        fm = _parse_frontmatter(content)
        assert fm.get("paths") is None
        assert fm.get("when_to_use") is None

    def test_skill_directory_returns_paths(self, tmp_path: Path) -> None:
        d = tmp_path / "cond-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: cond-skill\ndescription: Conditional\npaths:\n  - '*.ts'\n---\nbody",
            encoding="utf-8",
        )
        cfg = SootheConfig()
        cfg.skills = [str(d)]
        meta = resolve_skill_directory(cfg, "cond-skill")
        assert meta is not None
        assert meta.get("paths") == ["*.ts"]

    def test_skill_directory_returns_when_to_use(self, tmp_path: Path) -> None:
        d = tmp_path / "wtu-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: wtu-skill\ndescription: D\nwhen_to_use: Use me for docs\n---\nbody",
            encoding="utf-8",
        )
        cfg = SootheConfig()
        cfg.skills = [str(d)]
        meta = resolve_skill_directory(cfg, "wtu-skill")
        assert meta is not None
        assert meta.get("when_to_use") == "Use me for docs"
