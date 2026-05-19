"""Tests for workspace glob gitignore filtering (deepagents glob API)."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends.utils import truncate_if_too_long

from soothe.core.workspace.backend import NormalizedPathBackend


def test_glob_api_respects_gitignore_and_essential_excludes(tmp_path: Path) -> None:
    """``glob()`` must apply gitignore patterns and essential directory excludes."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (ws / "README.md").write_text("hello", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "pkg").mkdir()
    (ws / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")

    backend = NormalizedPathBackend(root_dir=str(ws), virtual_mode=True, max_file_size_mb=10)
    result = backend.glob("**/*", "/")
    assert result.error is None
    paths = [m.get("path", "") for m in result.matches or [] if not m.get("truncated")]
    assert not any(".git" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert any("README.md" in p for p in paths)
    assert len(paths) <= backend.DEFAULT_GLOB_MAX_RESULTS


def test_glob_api_output_size_matches_filtered_cap(tmp_path: Path) -> None:
    """Unfiltered globs can exceed tool limits; filtered globs stay small."""
    ws = tmp_path / "repo"
    ws.mkdir()
    for i in range(200):
        (ws / f"file_{i}.txt").write_text("x", encoding="utf-8")

    backend = NormalizedPathBackend(root_dir=str(ws), virtual_mode=True, max_file_size_mb=10)
    filtered = backend.glob("**/*", "/")
    raw = super(NormalizedPathBackend, backend).glob("**/*", "/")
    filtered_paths = [m.get("path", "") for m in filtered.matches or [] if not m.get("truncated")]
    raw_paths = [m.get("path", "") for m in raw.matches or []]
    assert len(filtered_paths) <= backend.DEFAULT_GLOB_MAX_RESULTS
    assert len(raw_paths) > backend.DEFAULT_GLOB_MAX_RESULTS
    assert len(str(truncate_if_too_long(filtered_paths))) < len(str(truncate_if_too_long(raw_paths)))
