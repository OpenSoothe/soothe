"""Workspace management package - unified workspace resolution, validation, and backend.

Heavy backends (``deepagents``) load only when accessed via attribute lookup, so
daemon startup can import resolution helpers without pulling LangChain providers.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "WorkspaceAwareBackend",
    "cleanup_anonymous_workspaces",
    "cleanup_legacy_per_loop_workspaces",
    "clear_virtual_mode_context",
    "compute_workspace_id",
    "compute_scoped_workspace_dir_name",
    "get_git_status",
    "normalize_user_id",
    "resolve_loop_workspace",
    "resolve_persisted_loop_workspace",
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "resolve_daemon_workspace",
    "resolve_user_workspace",
    "resolve_virtual_path",
    "resolve_workspace_for_stream",
    "set_virtual_mode_context",
    "validate_client_workspace",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "resolve_daemon_workspace": (".resolution", "resolve_daemon_workspace"),
    "resolve_user_workspace": (".resolution", "resolve_user_workspace"),
    "compute_workspace_id": (".resolution", "compute_workspace_id"),
    "normalize_user_id": (".loop_workspace", "normalize_user_id"),
    "compute_scoped_workspace_dir_name": (".loop_workspace", "compute_scoped_workspace_dir_name"),
    "resolve_loop_workspace": (".loop_workspace", "resolve_loop_workspace"),
    "resolve_persisted_loop_workspace": (".loop_workspace", "resolve_persisted_loop_workspace"),
    "cleanup_anonymous_workspaces": (".resolution", "cleanup_anonymous_workspaces"),
    "cleanup_legacy_per_loop_workspaces": (".resolution", "cleanup_legacy_per_loop_workspaces"),
    "validate_client_workspace": (".resolution", "validate_client_workspace"),
    "get_git_status": (".resolution", "get_git_status"),
    "ResolvedWorkspace": (".stream_resolution", "ResolvedWorkspace"),
    "resolve_workspace_for_stream": (".stream_resolution", "resolve_workspace_for_stream"),
    "WorkspaceAwareBackend": (".backend", "WorkspaceAwareBackend"),
    "NormalizedPathBackend": (".backend", "NormalizedPathBackend"),
    "FrameworkFilesystem": (".framework_filesystem", "FrameworkFilesystem"),
    "get_virtual_home": (".virtual_home", "get_virtual_home"),
    "get_virtual_mode": (".virtual_home", "get_virtual_mode"),
    "set_virtual_mode_context": (".virtual_home", "set_virtual_mode_context"),
    "clear_virtual_mode_context": (".virtual_home", "clear_virtual_mode_context"),
    "resolve_virtual_path": (".virtual_home", "resolve_virtual_path"),
    "get_virtual_home_relative_path": (".virtual_home", "get_virtual_home_relative_path"),
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
