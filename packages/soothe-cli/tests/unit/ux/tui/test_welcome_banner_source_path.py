"""Tests for welcome-banner source path selection."""

from __future__ import annotations

from pathlib import Path

from soothe_cli.tui.widgets.welcome import resolve_source_display_path


def test_source_path_prefers_workspace_over_editable_path() -> None:
    """Banner source row should prefer session workspace path."""
    workspace = str(Path.home() / "Workspace" / "project")
    result = resolve_source_display_path(
        workspace_path=workspace,
        editable_path="~/Workspace/mirasurf/soothe/packages/soothe",
    )
    assert result == "~/Workspace/project"


def test_source_path_falls_back_to_editable_path() -> None:
    """Editable install path is used when workspace is missing."""
    result = resolve_source_display_path(
        workspace_path=None,
        editable_path="~/Workspace/mirasurf/soothe/packages/soothe",
    )
    assert result == "~/Workspace/mirasurf/soothe/packages/soothe"
