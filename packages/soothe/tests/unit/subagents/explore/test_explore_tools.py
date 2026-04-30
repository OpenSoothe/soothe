"""Tests for explore subagent read-only tool factory."""

from __future__ import annotations

import tempfile
from pathlib import Path

from soothe.subagents.explore.tools import get_explore_tools


def test_get_explore_tools_includes_file_info() -> None:
    """Explore uses Soothe middleware readonly set including file_info."""
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


def test_mutating_tools_not_exposed() -> None:
    """Explore must not expose write/edit/delete/execute."""
    td = tempfile.mkdtemp()
    tools = get_explore_tools(workspace=td, allow_paths_outside_workspace=False)
    names = {t.name for t in tools}
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "execute" not in names
    assert "delete_file" not in names
