"""Soothe workspace: loop resolution + re-exports of nano CoreAgent helpers."""

from __future__ import annotations

from typing import Any

from soothe.foundation.workspace.core_resolution import (
    WorkspacePrecedence,
    resolve_workspace,
)
from soothe.foundation.workspace.loop_workspace import (
    compute_scoped_workspace_dir_name,
    normalize_user_id,
    resolve_loop_workspace,
    resolve_persisted_loop_workspace,
)
from soothe.foundation.workspace.resolution import (
    cleanup_anonymous_workspaces,
    resolve_daemon_workspace,
    translate_client_path_to_container,
    translate_container_path_to_client,
    validate_client_workspace,
)

__all__ = [
    "WorkspacePrecedence",
    "cleanup_anonymous_workspaces",
    "compute_scoped_workspace_dir_name",
    "normalize_user_id",
    "resolve_daemon_workspace",
    "resolve_loop_workspace",
    "resolve_persisted_loop_workspace",
    "translate_client_path_to_container",
    "translate_container_path_to_client",
    "validate_client_workspace",
    "resolve_workspace",
]


def __getattr__(name: str) -> Any:
    """Lazy-load CoreAgent workspace helpers from soothe_nano."""
    from importlib import import_module

    return getattr(import_module("soothe_nano.workspace"), name)
