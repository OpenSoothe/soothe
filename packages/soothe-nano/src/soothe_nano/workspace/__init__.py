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
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "resolve_workspace_for_stream",
    "resolve_workspace_for_tool_execution",
    "set_virtual_mode_context",
    "get_workspace_backend",
    "clear_virtual_mode_context",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
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
