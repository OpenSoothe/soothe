"""Tests for SkillWarehouse scan and dedupe behavior."""

from __future__ import annotations

from pathlib import Path

from soothe.foundation.skillify.warehouse import SkillWarehouse


def _write_skill(skill_dir: Path, *, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_scan_dedupes_by_skill_name_with_last_wins(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    builtin = tmp_path / "builtin"
    soothe = tmp_path / "soothe"
    _write_skill(agents / "shared-agent-dir", name="shared", description="from-agents")
    _write_skill(builtin / "shared-builtin-dir", name="shared", description="from-builtin")
    _write_skill(soothe / "shared-soothe-dir", name="shared", description="from-soothe")

    warehouse = SkillWarehouse(paths=[str(agents), str(builtin), str(soothe)])
    records = warehouse.scan()

    assert len(records) == 1
    assert records[0].name == "shared"
    assert records[0].description == "from-soothe"


def test_scan_dedupes_even_when_directory_names_differ(tmp_path: Path) -> None:
    low = tmp_path / "low"
    high = tmp_path / "high"
    _write_skill(low / "foo", name="same-name", description="low")
    _write_skill(high / "bar", name="same-name", description="high")

    warehouse = SkillWarehouse(paths=[str(low), str(high)])
    records = warehouse.scan()

    assert len(records) == 1
    assert records[0].name == "same-name"
    assert records[0].description == "high"
