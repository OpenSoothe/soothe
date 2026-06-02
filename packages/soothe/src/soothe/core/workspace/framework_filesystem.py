"""Framework-wide filesystem backend singleton."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol

    from soothe.config import SootheConfig
    from soothe.protocols.policy import PolicyContext, PolicyProtocol

logger = logging.getLogger(__name__)

# Thread-safe workspace context for async execution (RFC-103)
# Each async task (thread execution) has its own context, preventing cross-thread contamination
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)


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
    _root_dir: Path | None = None
    _policy: PolicyProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: PolicyProtocol | None = None,
    ) -> BackendProtocol:
        """Initialize the singleton filesystem backend.

        Args:
            config: Soothe configuration.
            policy: Optional security policy for access control.

        Returns:
            Initialized FilesystemBackend instance (workspace-aware wrapper).
        """
        from soothe.core.workspace.normalized_backend import WorkspaceAwareBackend
        from soothe.core.workspace.resolution import resolve_daemon_workspace

        # Use daemon workspace (TEMP unless SOOTHE_WORKSPACE set) as default
        resolved_workspace = resolve_daemon_workspace()

        # virtual_mode semantics (documented clearly, not as a "bug"):
        # - True: All paths treated as virtual under root_dir (sandboxed)
        #         Paths like "/etc/passwd" become "{root}/etc/passwd"
        # - False: Absolute paths used as-is, relative paths resolve under root
        #          Paths like "/etc/passwd" write to real /etc/passwd
        virtual_mode = not config.security.allow_paths_outside_workspace

        max_file_size_mb = 10
        if hasattr(config, "filesystem_middleware") and hasattr(
            config.filesystem_middleware, "max_file_size_mb"
        ):
            max_file_size_mb = config.filesystem_middleware.max_file_size_mb

        # Use workspace-aware backend that reads from ContextVar (RFC-103)
        cls._instance = WorkspaceAwareBackend(
            default_root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        cls._root_dir = resolved_workspace
        cls._policy = policy

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
    def check_policy(
        cls,
        file_path: str,
        operation: str,
        policy_context: PolicyContext | None = None,
    ) -> None:
        """Check security policy for a file operation.

        This provides an additional security layer for paths outside workspace
        when virtual_mode=False (allow_paths_outside_workspace=True).

        Args:
            file_path: File path to check.
            operation: Operation type ("read", "write", "edit").
            policy_context: Optional policy context.

        Raises:
            ValueError: If access denied by policy.
        """
        if cls._policy is None or policy_context is None:
            return

        # Get the resolved path from backend
        backend = cls.get()
        resolved = backend._resolve_path(file_path)

        # Check if path is outside workspace
        try:
            resolved.relative_to(cls._root_dir)
            # Under workspace - no policy check needed (backend handles it)
            logger.debug("Path %s is under workspace, no policy check needed", resolved)
        except ValueError:
            # Outside workspace - check policy
            from soothe.protocols.policy import ActionRequest

            action = ActionRequest(
                action_type="tool_call",
                tool_name=f"fs_{operation}",
                tool_args={"file_path": str(resolved)},
            )
            decision = cls._policy.check(action, policy_context)
            if decision.verdict == "deny":
                error_msg = f"Access denied: Path '{resolved}' is outside workspace. Reason: {decision.reason}"
                raise ValueError(error_msg) from None
            logger.debug("Policy check passed for path outside workspace: %s", resolved)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance.

        Used for testing and re-initialization.
        """
        cls._instance = None
        cls._root_dir = None
        cls._policy = None
        logger.debug("FrameworkFilesystem reset")

    # -----------------------------------------------------------------------
    # Thread-Aware Workspace Methods (RFC-103)
    # -----------------------------------------------------------------------

    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Token[Path | None]:
        """Set workspace for current async context.

        Called by WorkspaceContextMiddleware at stream start to establish
        thread-specific workspace for all subsequent file operations.

        Args:
            workspace: Workspace path (Path or str).

        Returns:
            A ContextVar Token that can be passed to clear_current_workspace
            to safely restore the previous value.
        """
        from soothe.core.workspace.context import get_workspace_context, set_workspace_context

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
        from soothe.core.workspace.context import get_workspace_context

        return get_workspace_context().workspace

    @classmethod
    def clear_current_workspace(cls, token: Token[Path | None] | None = None) -> None:
        """Clear workspace context at stream end.

        Called by WorkspaceContextMiddleware to prevent context leaks
        across stream boundaries.

        Args:
            token: If provided, uses ContextVar.reset(token) to safely restore
                the previous value. Otherwise falls back to clearing context.
        """
        from soothe.core.workspace.context import reset_workspace_context

        reset_workspace_context(token)

    @classmethod
    def resolve_path_dynamic(cls, file_path: str) -> Path:
        """Resolve file path against current workspace or fallback.

        Resolution order:
        1. If ContextVar has workspace, resolve relative paths against it
        2. Else use cls._root_dir (daemon default)
        3. Absolute paths used as-is (with policy check if outside workspace)

        Args:
            file_path: File path to resolve.

        Returns:
            Resolved absolute path.
        """
        path = Path(file_path)

        # Absolute paths: use as-is
        if path.is_absolute():
            return path

        # Relative paths: resolve against current workspace or fallback
        workspace = cls.get_current_workspace() or cls._root_dir
        if workspace is None:
            raise RuntimeError("No workspace available ( neither thread nor daemon default)")
        return workspace / file_path
