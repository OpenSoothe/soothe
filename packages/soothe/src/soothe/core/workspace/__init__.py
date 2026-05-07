"""Workspace management package - unified workspace resolution, validation, and backend.

This package provides:
- Workspace resolution for daemon and client contexts
- Workspace validation and security checks
- Workspace-aware filesystem backends
- Framework-wide filesystem singleton
- Virtual home directory resolution (IG-405)

Architecture:
- resolution.py: Daemon/client workspace validation
- stream_resolution.py: Unified stream resolution for runner
- backend.py: Workspace-aware backend wrapper
- framework_filesystem.py: Singleton filesystem backend
- virtual_home.py: Virtual home context for virtual mode (IG-405)

Usage:
    from soothe.core.workspace import (
        resolve_daemon_workspace,
        validate_client_workspace,
        resolve_workspace_for_stream,
        FrameworkFilesystem,
        WorkspaceAwareBackend,
        get_virtual_home,
        get_virtual_mode,
    )

RFC-103: Thread-specific workspace isolation
RFC-104: Workspace validation and resolution
IG-405: Virtual file system backend integration
"""

from __future__ import annotations

# Workspace-aware backend
from .backend import (
    NormalizedPathBackend,
    WorkspaceAwareBackend,
)

# Framework filesystem singleton
from .framework_filesystem import FrameworkFilesystem

# Workspace resolution and validation
from .resolution import (
    get_git_status,  # Git status collection utility
    resolve_daemon_workspace,
    resolve_loop_daemon_workspace,
    validate_client_workspace,
)

# Unified stream resolution
from .stream_resolution import (
    ResolvedWorkspace,
    resolve_workspace_for_stream,
)

# Virtual home resolution (IG-405)
from .virtual_home import (
    clear_virtual_mode_context,
    get_virtual_home,
    get_virtual_home_relative_path,
    get_virtual_mode,
    resolve_virtual_path,
    set_virtual_mode_context,
)

__all__ = [
    # Resolution and validation
    "resolve_daemon_workspace",
    "resolve_loop_daemon_workspace",
    "validate_client_workspace",
    "get_git_status",
    # Stream resolution
    "ResolvedWorkspace",
    "resolve_workspace_for_stream",
    # Backend
    "WorkspaceAwareBackend",
    "NormalizedPathBackend",
    # Framework filesystem
    "FrameworkFilesystem",
    # Virtual home (IG-405)
    "get_virtual_home",
    "get_virtual_mode",
    "set_virtual_mode_context",
    "clear_virtual_mode_context",
    "resolve_virtual_path",
    "get_virtual_home_relative_path",
]
