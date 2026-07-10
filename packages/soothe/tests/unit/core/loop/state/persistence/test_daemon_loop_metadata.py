"""Tests for daemon loop metadata preservation across checkpoint writes."""

from __future__ import annotations

from soothe.foundation.sloop.state.persistence.daemon_loop_metadata import (
    extract_daemon_loop_metadata,
    merge_daemon_loop_metadata,
)


def test_extract_daemon_loop_metadata_filters_strange_loop_fields() -> None:
    data = {
        "loop_id": "loop-1",
        "status": "running",
        "current_workspace": "/var/lib/soothe/workspaces/project",
        "client_workspace": "/Users/me/project",
        "workspace_mapping": {"host_root": "/Users/me", "container_root": "/var/lib/soothe/workspaces"},
        "goal_history": [{"goal_id": "g1"}],
    }
    extracted = extract_daemon_loop_metadata(data)
    assert extracted == {
        "current_workspace": "/var/lib/soothe/workspaces/project",
        "client_workspace": "/Users/me/project",
        "workspace_mapping": {
            "host_root": "/Users/me",
            "container_root": "/var/lib/soothe/workspaces",
        },
    }


def test_merge_daemon_loop_metadata_overlays_preserved_fields() -> None:
    checkpoint_data = {
        "loop_id": "loop-1",
        "status": "running",
        "goal_history": [],
    }
    preserved = {
        "current_workspace": "/var/lib/soothe/workspaces/project",
        "client_workspace": "/Users/me/project",
    }
    merged = merge_daemon_loop_metadata(checkpoint_data, preserved)
    assert merged["current_workspace"] == "/var/lib/soothe/workspaces/project"
    assert merged["client_workspace"] == "/Users/me/project"
    assert merged["goal_history"] == []


def test_merge_daemon_loop_metadata_noop_when_empty() -> None:
    checkpoint_data = {"loop_id": "loop-1", "status": "idle"}
    assert merge_daemon_loop_metadata(checkpoint_data, {}) is checkpoint_data
