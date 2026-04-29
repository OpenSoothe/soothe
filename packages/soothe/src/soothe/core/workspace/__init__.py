"""Workspace management package - unified workspace resolution, validation, and backend.

This package provides:
- Workspace resolution for daemon and client contexts
- Workspace validation and security checks
- Workspace-aware filesystem backends
- Framework-wide filesystem singleton

Architecture:
- resolution.py: Daemon/client workspace validation
- stream_resolution.py: Unified stream resolution for runner
- backend.py: Workspace-aware backend wrapper
- framework_filesystem.py: Singleton filesystem backend

Usage:
    from soothe.core.workspace import (
        resolve_daemon_workspace,
        validate_client_workspace,
        resolve_workspace_for_stream,
        FrameworkFilesystem,
        WorkspaceAwareBackend,
    )

RFC-103: Thread-specific workspace isolation
RFC-104: Workspace validation and resolution
"""

from __future__ import annotations

# Workspace-aware backend
from .backend import (
    NormalizedPathBackend,
    WorkspaceAwareBackend,
    create_workspace_aware_backend,
)

# Framework filesystem singleton
from .framework_filesystem import FrameworkFilesystem

# Workspace resolution and validation
from .path_normalization import strict_workspace_path
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

__all__ = [
    # Resolution and validation
    "resolve_daemon_workspace",
    "resolve_loop_daemon_workspace",
    "validate_client_workspace",
    "get_git_status",
    "strict_workspace_path",
    # Stream resolution
    "ResolvedWorkspace",
    "resolve_workspace_for_stream",
    # Backend
    "WorkspaceAwareBackend",
    "NormalizedPathBackend",
    "create_workspace_aware_backend",
    # Framework filesystem
    "FrameworkFilesystem",
]
