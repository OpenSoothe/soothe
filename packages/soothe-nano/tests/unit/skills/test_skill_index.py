"""Tests for ``soothe.skills.index``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from soothe_nano.skills.index import SkillIndex


def _make_skill(tmp_path: Path, name: str, description: str = "desc") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ntags: test\n---\n# {name}\n",
        encoding="utf-8",
    )
    return d


def test_rebuild_discovers_skills(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "alpha")
    _make_skill(root, "beta")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        entries = index.rebuild_if_stale()

    assert len(entries) == 2
    names = [e.name for e in entries]
    assert "alpha" in names
    assert "beta" in names


def test_rebuild_only_reparses_changed(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "stable")
    _make_skill(root, "changing")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        index.rebuild_if_stale()

        # Update changing skill
        (root / "changing" / "SKILL.md").write_text(
            "---\nname: changing\ndescription: updated\ntags: new\n---\n# changed\n",
            encoding="utf-8",
        )

        entries = index.rebuild_if_stale()

    changing = next(e for e in entries if e.name == "changing")
    assert changing.description == "updated"
    assert changing.tags == "new"


def test_rebuild_removes_deleted_skills(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "keep")
    removable = _make_skill(root, "remove")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        entries = index.rebuild_if_stale()
        assert len(entries) == 2

        import shutil

        shutil.rmtree(removable)
        entries = index.rebuild_if_stale()

    assert len(entries) == 1
    assert entries[0].name == "keep"


def test_resolve_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "MySkill")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        index.rebuild_if_stale()

    assert index.resolve("myskill") is not None
    assert index.resolve("MYSKILL") is not None
    assert index.resolve("MySkill") is not None


def test_wire_entries_excludes_path(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "wired")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        index.rebuild_if_stale()

    wire = index.wire_entries()
    assert len(wire) == 1
    assert wire[0]["name"] == "wired"
    assert "path" not in wire[0]
    assert wire[0]["source"] == "user"


def test_persist_and_load_cache(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "cached")

    cache_file = tmp_path / "cache" / "skill_index.json"

    index = SkillIndex()
    with (
        patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)),
        patch("soothe_nano.skills.index._CACHE_FILE", cache_file),
    ):
        index.rebuild_if_stale()

    assert cache_file.exists()

    # New index should load from cache
    index2 = SkillIndex()
    with (
        patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)),
        patch("soothe_nano.skills.index._CACHE_FILE", cache_file),
    ):
        index2._load_cache()

    assert "cached" in index2._entries


def test_multiple_roots(tmp_path: Path) -> None:
    root1 = tmp_path / "agents_skills"
    root1.mkdir()
    _make_skill(root1, "from-agents")

    root2 = tmp_path / "soothe_skills"
    root2.mkdir()
    _make_skill(root2, "from-soothe")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root1, "user"), (root2, "user"))):
        entries = index.rebuild_if_stale()

    names = [e.name for e in entries]
    assert "from-agents" in names
    assert "from-soothe" in names


def test_entries_sorted_by_name(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "zebra")
    _make_skill(root, "alpha")
    _make_skill(root, "middle")

    index = SkillIndex()
    with patch("soothe_nano.skills.index._SKILL_ROOTS", ((root, "user"),)):
        entries = index.rebuild_if_stale()

    names = [e.name for e in entries]
    assert names == sorted(names, key=str.lower)


def test_dedup_across_roots(tmp_path: Path) -> None:
    """When the same skill name exists in multiple roots, the later root wins."""
    soothe_skills = tmp_path / "soothe_skills"
    soothe_skills.mkdir()
    _make_skill(soothe_skills, "dup", description="from-soothe")

    agents_skills = tmp_path / "agents_skills"
    agents_skills.mkdir()
    _make_skill(agents_skills, "dup", description="from-agents")

    index = SkillIndex()
    with patch(
        "soothe_nano.skills.index._SKILL_ROOTS",
        ((soothe_skills, "user"), (agents_skills, "user")),
    ):
        entries = index.rebuild_if_stale()

    assert len(entries) == 1
    assert entries[0].description == "from-agents"


def test_agents_skills_root_included(tmp_path: Path) -> None:
    """Verify ~/.agents/skills and built_in_skills are in _SKILL_ROOTS."""
    from soothe_nano.skills.index import _BUILTIN_SKILLS_DIR, _SKILL_ROOTS

    root_paths = [r for r, _ in _SKILL_ROOTS]
    agents_root = Path.home() / ".agents" / "skills"
    soothe_root = Path.home() / ".soothe" / "skills"
    assert agents_root in root_paths
    assert _BUILTIN_SKILLS_DIR in root_paths
    assert soothe_root in root_paths


def test_default_root_precedence_soothe_over_builtin_over_agents(tmp_path: Path) -> None:
    """Default roots should be ordered by effective priority (last-wins)."""
    from soothe_nano.skills.index import _BUILTIN_SKILLS_DIR, _SKILL_ROOTS

    root_paths = [r for r, _ in _SKILL_ROOTS]
    agents_root = Path.home() / ".agents" / "skills"
    soothe_root = Path.home() / ".soothe" / "skills"
    assert root_paths.index(agents_root) < root_paths.index(_BUILTIN_SKILLS_DIR)
    assert root_paths.index(_BUILTIN_SKILLS_DIR) < root_paths.index(soothe_root)


def test_source_builtin_vs_user(tmp_path: Path) -> None:
    """Built-in skills get source='builtin'; user skills get source='user'."""
    builtin_root = tmp_path / "built_in_skills"
    builtin_root.mkdir()
    _make_skill(builtin_root, "core-skill")

    user_root = tmp_path / "user_skills"
    user_root.mkdir()
    _make_skill(user_root, "my-skill")

    index = SkillIndex()
    with patch(
        "soothe_nano.skills.index._SKILL_ROOTS",
        ((builtin_root, "builtin"), (user_root, "user")),
    ):
        entries = index.rebuild_if_stale()

    core = next(e for e in entries if e.name == "core-skill")
    my = next(e for e in entries if e.name == "my-skill")
    assert core.source == "builtin"
    assert my.source == "user"


def test_dedup_uses_frontmatter_name_not_directory_name(tmp_path: Path) -> None:
    """Collision dedupe should use SKILL frontmatter name across roots."""
    low_root = tmp_path / "agents"
    low_root.mkdir()
    _make_skill(low_root, "alpha-dir", description="from-agents")
    (low_root / "alpha-dir" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: from-agents\n---\n# shared\n",
        encoding="utf-8",
    )

    high_root = tmp_path / "soothe"
    high_root.mkdir()
    _make_skill(high_root, "beta-dir", description="from-soothe")
    (high_root / "beta-dir" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: from-soothe\n---\n# shared\n",
        encoding="utf-8",
    )

    index = SkillIndex()
    with patch(
        "soothe_nano.skills.index._SKILL_ROOTS",
        ((low_root, "user"), (high_root, "user")),
    ):
        entries = index.rebuild_if_stale()

    assert len(entries) == 1
    assert entries[0].name == "shared"
    assert entries[0].description == "from-soothe"
