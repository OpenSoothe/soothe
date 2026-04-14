"""Tests for built-in skills discovery and loading."""

from pathlib import Path

from soothe.skills import get_built_in_skills_paths


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


def test_create_subagent_skill_exists() -> None:
    """Test that the create-subagent skill is included."""
    paths = get_built_in_skills_paths()

    skill_names = [Path(p).name for p in paths]
    assert "create-subagent" in skill_names, "create-subagent skill should be included in built-in skills"


def test_remember_skill_exists() -> None:
    """Test that the remember skill ships with built-ins."""
    paths = get_built_in_skills_paths()
    skill_names = [Path(p).name for p in paths]
    assert "remember" in skill_names, "remember skill should be included in built-in skills"


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
