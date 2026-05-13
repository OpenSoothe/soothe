"""Tests for explore subagent read-only tool factory."""

from __future__ import annotations

import tempfile
from pathlib import Path

from soothe.subagents.explore.tools import get_explore_tools


def test_get_explore_tools_includes_file_info_and_run_command() -> None:
    """Explore uses curated subset: filesystem recon + run_command shell tool."""
    td = tempfile.mkdtemp()
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    names = [t.name for t in tools]
    assert names == ["glob", "grep", "ls", "read_file", "file_info", "run_command"]


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
    """Callable explore backend uses NormalizedPathBackend: host paths under root resolve."""
    td = tempfile.mkdtemp()
    Path(td, "note.txt").write_text("hello", encoding="utf-8")
    from soothe.subagents.explore.tools import _create_thread_workspace_backend

    backend = _create_thread_workspace_backend(
        initial_workspace=td,
        allow_paths_outside_workspace=False,
    )(None)
    host = str(Path(td) / "note.txt")
    r1 = backend.read(host)
    assert not r1.error, r1.error
    assert r1.file_data is not None
    assert "hello" in r1.file_data["content"]
    r2 = backend.read("/note.txt")
    assert not r2.error, r2.error
    assert r2.file_data is not None
    assert "hello" in r2.file_data["content"]


def test_mutating_tools_not_exposed() -> None:
    """Explore exposes run_command but not write/edit/delete surgical tools."""
    td = tempfile.mkdtemp()
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    names = {t.name for t in tools}
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "run_command" in names
    assert "delete_file" not in names
    assert "apply_diff" not in names
