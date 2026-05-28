"""Tests for ``soothe.skills.index``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from soothe.skills.index import SkillIndex


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
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
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
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
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
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
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
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
        index.rebuild_if_stale()

    assert index.resolve("myskill") is not None
    assert index.resolve("MYSKILL") is not None
    assert index.resolve("MySkill") is not None


def test_wire_entries_excludes_path(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    _make_skill(root, "wired")

    index = SkillIndex()
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
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
        patch("soothe.skills.index._SKILL_ROOTS", (root,)),
        patch("soothe.skills.index._CACHE_FILE", cache_file),
    ):
        index.rebuild_if_stale()

    assert cache_file.exists()

    # New index should load from cache
    index2 = SkillIndex()
    with (
        patch("soothe.skills.index._SKILL_ROOTS", (root,)),
        patch("soothe.skills.index._CACHE_FILE", cache_file),
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
    with patch("soothe.skills.index._SKILL_ROOTS", (root1, root2)):
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
    with patch("soothe.skills.index._SKILL_ROOTS", (root,)):
        entries = index.rebuild_if_stale()

    names = [e.name for e in entries]
    assert names == sorted(names, key=str.lower)
