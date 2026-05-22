"""Tests for user workspace resolution."""

from pathlib import Path

import pytest

import soothe.config as soothe_config


def test_compute_workspace_id_authenticated_user() -> None:
    """Test workspace ID generation for authenticated users."""
    from soothe.core.workspace.resolution import compute_workspace_id

    # Same user + same workspace = same ID
    ws1 = compute_workspace_id("alice", "/Users/alice/Projects/app1")
    ws2 = compute_workspace_id("alice", "/Users/alice/Projects/app1")
    assert ws1 == ws2
    assert ws1.startswith("ws_")
    assert len(ws1) == 19  # "ws_" + 16 hex chars

    # Different workspace = different ID
    ws3 = compute_workspace_id("alice", "/Users/alice/Projects/app2")
    assert ws3 != ws1
    assert ws3.startswith("ws_")

    # Different user = different ID (even with same workspace)
    ws4 = compute_workspace_id("bob", "/Users/alice/Projects/app1")
    assert ws4 != ws1
    assert ws4.startswith("ws_")


def test_compute_workspace_id_anonymous_user() -> None:
    """Test workspace ID generation for anonymous users."""
    from soothe.core.workspace.resolution import compute_workspace_id

    # Anonymous user = anon_ prefix
    ws1 = compute_workspace_id(None, "/tmp/project")
    assert ws1.startswith("anon_")
    assert len(ws1) == 21  # "anon_" + 16 hex chars

    # Same workspace = same ID
    ws2 = compute_workspace_id(None, "/tmp/project")
    assert ws1 == ws2

    # Different workspace = different ID
    ws3 = compute_workspace_id(None, "/tmp/other")
    assert ws3 != ws1


def test_resolve_user_workspace_creates_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that resolve_user_workspace creates the workspace directory."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path))
    from soothe.core.workspace.resolution import resolve_user_workspace

    ws = resolve_user_workspace("alice", "/Users/alice/Projects/app", soothe_home=tmp_path)
    assert ws.is_dir()
    assert ws.parent.name == "workspaces"
    assert ws.name.startswith("ws_")


def test_resolve_user_workspace_anonymous_creates_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test anonymous workspace directory creation."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path))
    from soothe.core.workspace.resolution import resolve_user_workspace

    ws = resolve_user_workspace(None, "/tmp/project", soothe_home=tmp_path)
    assert ws.is_dir()
    assert ws.parent.name == "workspaces"
    assert ws.name.startswith("anon_")