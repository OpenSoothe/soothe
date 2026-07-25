"""Tests for setup scaffold phase."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from soothe_daemon.setup.paths import config_paths
from soothe_daemon.setup.scaffold import scaffold_configs


def test_scaffold_creates_three_files(tmp_path: Path) -> None:
    out = StringIO()
    result = scaffold_configs(tmp_path, stdout=out)

    assert sorted(result.created) == ["daemon", "nano", "soothe"]
    assert result.skipped == []
    paths = config_paths(tmp_path)
    for path in paths.values():
        assert path.is_file()
        assert path.stat().st_size > 0


def test_scaffold_skips_existing(tmp_path: Path) -> None:
    out = StringIO()
    scaffold_configs(tmp_path, stdout=out)
    nano = tmp_path / "nano.yml"
    original = nano.read_text(encoding="utf-8")
    nano.write_text(original + "\n# custom\n", encoding="utf-8")

    out2 = StringIO()
    result = scaffold_configs(tmp_path, stdout=out2)
    assert sorted(result.skipped) == ["daemon", "nano", "soothe"]
    assert result.created == []
    assert "# custom" in nano.read_text(encoding="utf-8")


def test_scaffold_force_overwrites(tmp_path: Path) -> None:
    scaffold_configs(tmp_path, stdout=StringIO())
    nano = tmp_path / "nano.yml"
    nano.write_text("providers: []\n", encoding="utf-8")

    result = scaffold_configs(tmp_path, force=True, stdout=StringIO())
    assert "nano" in result.overwritten
    assert "providers:" in nano.read_text(encoding="utf-8")
    assert nano.read_text(encoding="utf-8") != "providers: []\n"


def test_atomic_write_no_tmp_left(tmp_path: Path) -> None:
    from soothe_daemon.setup.atomic import atomic_write_text

    dest = tmp_path / "nano.yml"
    atomic_write_text(dest, "hello: world\n")
    assert dest.read_text(encoding="utf-8") == "hello: world\n"
    assert not (tmp_path / "nano.yml.tmp").exists()
