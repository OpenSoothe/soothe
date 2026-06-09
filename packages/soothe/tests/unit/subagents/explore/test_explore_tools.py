"""Tests for explore subagent read-only tool factory."""

from __future__ import annotations

import tempfile
from pathlib import Path

from soothe.subagents.explore.tools import get_explore_tools


def test_get_explore_tools_filesystem_only() -> None:
    """Explore uses curated read-only filesystem tools (no shell)."""
    td = tempfile.mkdtemp()
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    names = [t.name for t in tools]
    assert names == ["glob", "grep", "ls", "read_file", "file_info"]


def test_file_info_invokes_against_workspace_file() -> None:
    """file_info resolves workspace-relative paths (virtual_mode sandbox)."""
    td = tempfile.mkdtemp()
    Path(td, "x.txt").write_text("hello", encoding="utf-8")
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    fi = next(t for t in tools if t.name == "file_info")
    out = fi.invoke({"path": "x.txt"})
    assert "Size:" in out
    assert "x.txt" in out


def test_read_file_accepts_host_absolute_and_virtual_paths() -> None:
    """Explore backend uses NormalizedPathBackend: host paths under root resolve."""
    td = tempfile.mkdtemp()
    Path(td, "note.txt").write_text("hello", encoding="utf-8")
    from soothe.foundation.workspace.normalized_backend import get_workspace_backend

    backend = get_workspace_backend(
        Path(td),
        virtual_mode=True,
        max_file_size_mb=10,
    )
    host = str(Path(td) / "note.txt")
    r1 = backend.read(host)
    assert r1.error is None and r1.file_data is not None
    assert "hello" in r1.file_data["content"]
    r2 = backend.read("/note.txt")
    assert r2.error is None and r2.file_data is not None
    assert "hello" in r2.file_data["content"]


def test_mutating_and_shell_tools_not_exposed() -> None:
    """Explore does not expose write, edit, delete, or shell tools."""
    td = tempfile.mkdtemp()
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    names = {t.name for t in tools}
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "run_command" not in names
    assert "delete_file" not in names
    assert "apply_diff" not in names
