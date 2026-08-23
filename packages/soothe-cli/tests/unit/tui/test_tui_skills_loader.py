"""Tests for TUI skill SKILL.md loading and frontmatter stripping."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_cli.tui.skills.load import load_skill_content, strip_skill_frontmatter


def test_strip_skill_frontmatter_removes_yaml_block() -> None:
    """Frontmatter delimiters are removed from skill bodies."""
    raw = "---\nname: x\ndescription: y\n---\n\nBody here\n"
    assert strip_skill_frontmatter(raw).strip() == "Body here"


def test_load_skill_content_respects_containment(tmp_path: Path) -> None:
    """Paths outside allowed roots raise ``PermissionError``."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: d\n---\n\nx\n", encoding="utf-8"
    )

    allowed = [skill_dir.resolve()]
    text = load_skill_content(skill_dir, allowed_roots=allowed)
    assert text is not None
    assert "name: my-skill" in text

    outside = tmp_path / "evil" / "SKILL.md"
    outside.parent.mkdir()
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(PermissionError):
        load_skill_content(outside, allowed_roots=allowed)
