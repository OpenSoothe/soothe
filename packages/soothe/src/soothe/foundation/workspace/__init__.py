"""Workspace management package - unified workspace resolution, validation, and backend.

This package provides workspace-aware filesystem operations using the native
Soothe UnifiedFilesystem interface.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "WorkspaceAwareBackend",
    "WorkspaceContext",
    "WorkspacePrecedence",
    "cleanup_anonymous_workspaces",
    "clear_virtual_mode_context",
    "compute_scoped_workspace_dir_name",
    "get_git_status",
    "migrate_workspaces_to_data_dir",
    "normalize_user_id",
    "resolve_loop_workspace",
    "resolve_persisted_loop_workspace",
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "resolve_daemon_workspace",
    "resolve_workspace",
    "resolve_workspace_for_stream",
    "resolve_workspace_for_tool_execution",
    "set_virtual_mode_context",
    "translate_client_path_to_container",
    "translate_container_path_to_client",
    "validate_client_workspace",
    "get_workspace_backend",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "resolve_daemon_workspace": (".resolution", "resolve_daemon_workspace"),
    "normalize_user_id": (".loop_workspace", "normalize_user_id"),
    "compute_scoped_workspace_dir_name": (".loop_workspace", "compute_scoped_workspace_dir_name"),
    "resolve_loop_workspace": (".loop_workspace", "resolve_loop_workspace"),
    "resolve_persisted_loop_workspace": (".loop_workspace", "resolve_persisted_loop_workspace"),
    "cleanup_anonymous_workspaces": (".resolution", "cleanup_anonymous_workspaces"),
    "validate_client_workspace": (".resolution", "validate_client_workspace"),
    "translate_client_path_to_container": (".resolution", "translate_client_path_to_container"),
    "translate_container_path_to_client": (".resolution", "translate_container_path_to_client"),
    "get_git_status": (".resolution", "get_git_status"),
    "ResolvedWorkspace": (".stream_resolution", "ResolvedWorkspace"),
    "resolve_workspace_for_stream": (".stream_resolution", "resolve_workspace_for_stream"),
    "resolve_workspace_for_tool_execution": (
        ".runtime_resolution",
        "resolve_workspace_for_tool_execution",
    ),
    # Normalized backend
    "WorkspaceAwareBackend": (".normalized_backend", "WorkspaceAwareBackend"),
    "NormalizedPathBackend": (".normalized_backend", "NormalizedPathBackend"),
    "FrameworkFilesystem": (".framework_filesystem", "FrameworkFilesystem"),
    "get_workspace_backend": (".normalized_backend", "get_workspace_backend"),
    # Virtual home
    "get_virtual_home": (".virtual_home", "get_virtual_home"),
    "get_virtual_mode": (".virtual_home", "get_virtual_mode"),
    "set_virtual_mode_context": (".virtual_home", "set_virtual_mode_context"),
    "clear_virtual_mode_context": (".virtual_home", "clear_virtual_mode_context"),
    "get_virtual_home_relative_path": (".virtual_home", "get_virtual_home_relative_path"),
    # Unified context
    "WorkspaceContext": (".context", "WorkspaceContext"),
    # Shared resolution core
    "WorkspacePrecedence": (".core_resolution", "WorkspacePrecedence"),
    "resolve_workspace": (".core_resolution", "resolve_workspace"),
    # Migration
    "migrate_workspaces_to_data_dir": (".migration", "migrate_workspaces_to_data_dir"),
}


def __getattr__(name: str) -> Any:
    """Lazy-load workspace submodules to keep daemon import path lightweight."""
    spec = _LAZY_EXPORTS.get(name)
    if spec is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    module_name, attr_name = spec
    import importlib

    module = importlib.import_module(module_name, package=__name__)
    return getattr(module, attr_name)
