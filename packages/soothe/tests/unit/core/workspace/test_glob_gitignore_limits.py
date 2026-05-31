"""Tests for workspace glob gitignore filtering (WorkspaceFilesystem glob API)."""

from __future__ import annotations

from pathlib import Path

from soothe.core.filesystem.protocol import GlobResult
from soothe.core.filesystem.workspace import WorkspaceFilesystem


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

    # WorkspaceFilesystem has gitignore support
    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*")
    assert isinstance(result, GlobResult)
    assert result.error is None
    paths = result.matches or []
    # Essential excludes filter out .git and node_modules
    assert not any(".git" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert any("README.md" in p for p in paths)


def test_glob_respects_root_gitignore_patterns(tmp_path: Path) -> None:
    """Patterns from ``.gitignore`` (e.g. ``secret_dir/``) exclude matches during glob."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / ".gitignore").write_text("secret_dir/\n*.log\n", encoding="utf-8")
    (ws / "visible.txt").write_text("ok", encoding="utf-8")
    (ws / "secret_dir").mkdir()
    (ws / "secret_dir" / "hidden.txt").write_text("no", encoding="utf-8")
    (ws / "noise.log").write_text("no", encoding="utf-8")

    # WorkspaceFilesystem has gitignore support
    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*")
    assert isinstance(result, GlobResult)
    paths = result.matches or []
    assert any("visible.txt" in p for p in paths)
    assert not any("secret_dir" in p for p in paths)
    assert not any(".log" in p for p in paths)


def test_glob_api_output_size_matches_filtered_cap(tmp_path: Path) -> None:
    """Large workspaces return at most DEFAULT_GLOB_MAX_RESULTS entries."""
    ws = tmp_path / "repo"
    ws.mkdir()
    for i in range(200):
        (ws / f"file_{i}.txt").write_text("x", encoding="utf-8")

    # WorkspaceFilesystem has output size caps
    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*")
    assert isinstance(result, GlobResult)
    paths = result.matches or []
    # WorkspaceFilesystem caps results at DEFAULT_GLOB_MAX_RESULTS (50)
    assert len(paths) <= WorkspaceFilesystem.DEFAULT_GLOB_MAX_RESULTS
    assert result.truncated is True