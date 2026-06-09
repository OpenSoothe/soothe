"""Tests for workspace directory migration (RFC-621)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.foundation.workspace.migration import migrate_workspaces_to_data_dir


def test_migrate_moves_workspace_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Old workspace dirs under workspaces/ are moved to data/workspaces/."""
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))

    # Create old layout
    old_ws = tmp_path / "workspaces"
    (old_ws / "anonymous" / "ws_abc123").mkdir(parents=True)
    (old_ws / "alice" / "ws_def456").mkdir(parents=True)

    migrate_workspaces_to_data_dir()

    # Old dirs moved
    assert not (old_ws / "anonymous").exists()
    assert not (old_ws / "alice").exists()

    # New dirs exist
    new_ws = tmp_path / "data" / "workspaces"
    assert (new_ws / "anonymous" / "ws_abc123").is_dir()
    assert (new_ws / "alice" / "ws_def456").is_dir()


def test_migration_skips_when_new_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration is a no-op when data/workspaces/ already exists."""
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))

    # Create both old and new
    old_ws = tmp_path / "workspaces"
    (old_ws / "anonymous" / "ws_abc123").mkdir(parents=True)
    new_ws = tmp_path / "data" / "workspaces"
    new_ws.mkdir(parents=True)

    migrate_workspaces_to_data_dir()

    # Old dir still exists (not moved)
    assert (old_ws / "anonymous").is_dir()


def test_migration_skips_when_no_workspaces_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration is a no-op when workspaces/ doesn't exist."""
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))

    migrate_workspaces_to_data_dir()  # should not raise

    assert not (tmp_path / "data" / "workspaces").exists()


def test_migration_skips_docker_mount_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration skips when workspaces/ contains non-workspace content (Docker mount)."""
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))

    # Create Docker mount content
    old_ws = tmp_path / "workspaces"
    (old_ws / "project-a" / "src").mkdir(parents=True)  # not a ws_* pattern
    (old_ws / "anonymous" / "ws_abc123").mkdir(parents=True)

    migrate_workspaces_to_data_dir()

    # Docker mount content stays; workspace dir still there since mixed content
    assert (old_ws / "project-a").is_dir()
