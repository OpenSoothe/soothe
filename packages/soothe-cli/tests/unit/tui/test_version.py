"""Tests for TUI version resolution."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path

from soothe_cli.tui import _version


def test_parse_version_file_text_reads_semver() -> None:
    assert _version._parse_version_file_text("0.7.11\n") == "0.7.11"
    assert _version._parse_version_file_text("# comment\n0.8.0\n") == "0.8.0"


def test_read_repo_version_from_source_finds_monorepo_version(tmp_path: Path) -> None:
    repo_root = tmp_path / "soothe"
    package_root = repo_root / "packages" / "soothe-cli"
    package_root.mkdir(parents=True)
    (repo_root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

    assert _version._read_repo_version_from_source(package_root) == "1.2.3"


def test_resolve_version_prefers_repo_version_for_editable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "soothe"
    package_root = repo_root / "packages" / "soothe-cli"
    package_root.mkdir(parents=True)
    (repo_root / "VERSION").write_text("9.9.9\n", encoding="utf-8")

    monkeypatch.setattr(_version, "_editable_source_roots", lambda: [package_root])
    monkeypatch.setattr(
        _version,
        "version",
        lambda _pkg: (_ for _ in ()).throw(PackageNotFoundError("missing")),
    )

    assert _version._resolve_version() == "9.9.9"
