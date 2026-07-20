"""Tests for workspace glob gitignore filtering (WorkspaceFilesystem glob API)."""

from __future__ import annotations

import os
from pathlib import Path

from soothe_nano.filesystem.protocol import GlobResult
from soothe_nano.filesystem.workspace import WorkspaceFilesystem
from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend


def test_normalized_backend_glob_uses_workspace_filesystem(tmp_path: Path) -> None:
    """``NormalizedPathBackend`` must route glob through ``WorkspaceFilesystem``.

    Regression: production glob previously delegated to ``LocalFilesystem.glob``,
    which lacks gitignore filtering, has no result cap, and emits bare
    workspace-relative names. Tools that surface the result to the LLM (and any
    follow-up shell command using those paths) were misled by the mismatch.
    """
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (ws / "README.md").write_text("hello", encoding="utf-8")
    (ws / "ignored.txt").write_text("nope", encoding="utf-8")
    # Essential excludes should still apply.
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    backend = NormalizedPathBackend(root_dir=ws, virtual_mode=True)
    result = backend.glob("**/*", path="/")
    matches = [m["path"] for m in (result.matches or [])]

    assert matches, "expected at least one match"
    assert any("README.md" in p for p in matches)
    # gitignore must be applied via WorkspaceFilesystem
    assert not any("ignored.txt" in p for p in matches)
    # essential excludes (.git) must be honored
    assert not any(".git" in p for p in matches)
    # paths must be host-absolute (not virtual /-prefixed, not workspace-relative)
    for p in matches:
        assert os.path.isabs(p), f"path not host-absolute: {p!r}"
        assert p.startswith(str(ws.resolve())), f"path not under workspace: {p!r}"


def test_glob_emits_host_absolute_paths_in_virtual_mode(tmp_path: Path) -> None:
    """Glob output must be host-absolute even when virtual_mode is on.

    Virtual-prefixed paths (e.g. ``/README.md``) mislead the LLM into reusing
    them in shell commands, where ``/`` is the host filesystem root. Returning
    host-absolute paths keeps the output usable in both filesystem and shell
    tools.
    """
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "README.md").write_text("hello", encoding="utf-8")

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*.md")
    paths = result.matches or []

    assert paths, "expected at least one match"
    for p in paths:
        assert os.path.isabs(p), f"path not host-absolute: {p!r}"
        assert p.startswith(str(ws.resolve())), f"path not under workspace: {p!r}"
        assert not p.startswith("/README"), f"virtual '/'-prefix leaked into output: {p!r}"


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


def test_glob_empty_result_includes_workspace_hint(tmp_path: Path) -> None:
    """Empty glob results include actionable workspace context (IG-570)."""
    ws = tmp_path / "repo"
    ws.mkdir()

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*integration*.test.ts")

    assert result.matches == []
    assert result.error is not None
    assert "workspace root" in result.error
    assert "integration" in result.error
