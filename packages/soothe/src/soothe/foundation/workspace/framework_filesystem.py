"""Framework-wide filesystem backend singleton."""

from __future__ import annotations

import logging
from contextvars import Token
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_deepagents.backends.protocol import BackendProtocol

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class FrameworkFilesystem:
    """Singleton filesystem backend for all framework operations.

    Provides consistent path resolution and security across:
    - Tool operations (via middleware)
    - Framework operations (reports, checkpoints, manifests)
    - CLI operations (final reports, health checks)

    Uses FilesystemBackend directly with proper virtual_mode semantics.
    No wrapper or path conversion workarounds needed.
    """

    _instance: BackendProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: object | None = None,
    ) -> BackendProtocol:
        """Initialize the singleton filesystem backend.

        Args:
            config: Soothe configuration.
            policy: Reserved for backward compatibility.

        Returns:
            Initialized FilesystemBackend instance (workspace-aware wrapper).
        """
        from soothe.foundation.workspace.normalized_backend import WorkspaceAwareBackend
        from soothe.foundation.workspace.resolution import resolve_daemon_workspace
        from soothe.foundation.workspace.tool_path_resolution import (
            config_workspace_root,
            max_file_size_mb_for_filesystem_backend,
        )

        configured_root = config_workspace_root(config)
        resolved_workspace = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else resolve_daemon_workspace()
        )

        # virtual_mode semantics (documented clearly, not as a "bug"):
        # - True: All paths treated as virtual under root_dir (sandboxed)
        #         Paths like "/etc/passwd" become "{root}/etc/passwd"
        # - False: Absolute paths used as-is, relative paths resolve under root
        #          Paths like "/etc/passwd" write to real /etc/passwd
        virtual_mode = not config.security.allow_paths_outside_workspace

        max_file_size_mb = max_file_size_mb_for_filesystem_backend(config)

        # Use workspace-aware backend that reads from ContextVar (RFC-103)
        cls._instance = WorkspaceAwareBackend(
            default_root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

        logger.info(
            "FrameworkFilesystem initialized: root=%s virtual_mode=%s (workspace-aware)",
            resolved_workspace,
            virtual_mode,
        )

        return cls._instance

    @classmethod
    def get(cls) -> BackendProtocol:
        """Get the singleton filesystem backend.

        Returns:
            BackendProtocol instance (workspace-aware wrapper).

        Raises:
            RuntimeError: If backend not initialized.
        """
        if cls._instance is None:
            raise RuntimeError("FrameworkFilesystem not initialized. Call initialize() first.")
        return cls._instance

    @classmethod
    # -----------------------------------------------------------------------
    # Thread-Aware Workspace Methods (RFC-103)
    # -----------------------------------------------------------------------

    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Token:
        """Set workspace for current async context.

        Called by WorkspaceContextMiddleware at stream start to establish
        thread-specific workspace for all subsequent file operations.

        Args:
            workspace: Workspace path (Path or str).

        Returns:
            A ContextVar Token that can be passed to clear_current_workspace
            to safely restore the previous value.
        """
        from soothe.foundation.workspace.context import get_workspace_context, set_workspace_context

        ws_path = Path(workspace) if isinstance(workspace, str) else workspace
        ctx = get_workspace_context()
        return set_workspace_context(
            workspace=ws_path,
            virtual_mode=ctx.virtual_mode,
        )

    @classmethod
    def get_current_workspace(cls) -> Path | None:
        """Get workspace for current async context.

        Returns:
            Current workspace Path, or None if not set (fallback to daemon default).
        """
        from soothe.foundation.workspace.context import get_workspace_context

        return get_workspace_context().workspace

    @classmethod
    def clear_current_workspace(cls, token: Token | None = None) -> None:
        """Clear workspace context at stream end.

        Called by WorkspaceContextMiddleware to prevent context leaks
        across stream boundaries.

        Args:
            token: If provided, uses ContextVar.reset(token) to safely restore
                the previous value. Otherwise falls back to clearing context.
        """
        from soothe.foundation.workspace.context import reset_workspace_context

        reset_workspace_context(token)

