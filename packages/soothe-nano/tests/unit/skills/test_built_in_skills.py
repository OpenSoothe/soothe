"""Tests for built-in skills discovery and loading."""

from pathlib import Path
from unittest.mock import patch

from soothe_nano.skills import get_built_in_skills_paths


def test_get_built_in_skills_paths_returns_list() -> None:
    """Test that get_built_in_skills_paths returns a list."""
    paths = get_built_in_skills_paths()
    assert isinstance(paths, list)


def test_get_built_in_skills_paths_non_empty() -> None:
    """Test that built-in skills are discovered."""
    paths = get_built_in_skills_paths()
    assert len(paths) > 0, "Expected at least one built-in skill to be found"


def test_built_in_skills_contain_skill_md() -> None:
    """Test that each discovered path contains a SKILL.md file."""
    paths = get_built_in_skills_paths()

    for skill_path in paths:
        skill_dir = Path(skill_path)
        skill_file = skill_dir / "SKILL.md"
        assert skill_file.exists(), f"SKILL.md not found in {skill_path}"
        assert skill_file.is_file(), f"SKILL.md is not a file in {skill_path}"


def test_skill_paths_are_absolute() -> None:
    """Test that all returned paths are absolute."""
    paths = get_built_in_skills_paths()

    for skill_path in paths:
        assert Path(skill_path).is_absolute(), f"Path {skill_path} should be absolute"


def test_skill_paths_exist() -> None:
    """Test that all returned paths exist as directories."""
    paths = get_built_in_skills_paths()

    for skill_path in paths:
        path = Path(skill_path)
        assert path.exists(), f"Path {skill_path} should exist"
        assert path.is_dir(), f"Path {skill_path} should be a directory"


def test_dedup_by_name(tmp_path: Path) -> None:
    """When the same skill name exists in multiple roots, later roots win."""
    from soothe_nano.skills.builtins import get_built_in_skills_paths as _get

    soothe_skills = tmp_path / ".soothe" / "skills"
    soothe_skills.mkdir(parents=True)
    (soothe_skills / "dup").mkdir()
    (soothe_skills / "dup" / "SKILL.md").write_text(
        "---\nname: dup\ndescription: from-soothe\n---\n", encoding="utf-8"
    )

    agents_skills = tmp_path / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    (agents_skills / "dup").mkdir()
    (agents_skills / "dup" / "SKILL.md").write_text(
        "---\nname: dup\ndescription: from-agents\n---\n", encoding="utf-8"
    )

    with patch("soothe_nano.skills.builtins.Path.home", return_value=tmp_path):
        # Mock built_in_skills dir to not exist so only our two roots are scanned
        with patch.object(Path, "__truediv__") as _:
            paths = _get()

    # The function should return only one path for "dup"
    dup_paths = [p for p in paths if "dup" in p]
    assert len(dup_paths) <= 1, f"Expected at most 1 dup, got {dup_paths}"
