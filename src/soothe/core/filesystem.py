"""Framework-wide filesystem backend singleton."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.backends.filesystem import FilesystemBackend

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.protocols.policy import PolicyContext, PolicyProtocol

logger = logging.getLogger(__name__)


class FrameworkFilesystem:
    """Singleton filesystem backend for all framework operations.

    Provides consistent path resolution and security across:
    - Tool operations (via middleware)
    - Framework operations (reports, checkpoints, manifests)
    - CLI operations (final reports, health checks)

    Uses deepagents FilesystemBackend directly with proper virtual_mode semantics.
    No wrapper or path conversion workarounds needed.
    """

    _instance: FilesystemBackend | None = None
    _root_dir: Path | None = None
    _policy: PolicyProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: PolicyProtocol | None = None,
    ) -> FilesystemBackend:
        """Initialize the singleton filesystem backend.

        Args:
            config: Soothe configuration.
            policy: Optional security policy for access control.

        Returns:
            Initialized FilesystemBackend instance.
        """
        from soothe.utils import expand_path

        resolved_workspace = expand_path(config.workspace_dir)

        # virtual_mode semantics (documented clearly, not as a "bug"):
        # - True: All paths treated as virtual under root_dir (sandboxed)
        #         Paths like "/etc/passwd" become "{root}/etc/passwd"
        # - False: Absolute paths used as-is, relative paths resolve under root
        #          Paths like "/etc/passwd" write to real /etc/passwd
        virtual_mode = not config.security.allow_paths_outside_workspace

        max_file_size_mb = 10
        if hasattr(config, "execution") and hasattr(config.execution, "max_file_size_mb"):
            max_file_size_mb = config.execution.max_file_size_mb

        cls._instance = FilesystemBackend(
            root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        cls._root_dir = resolved_workspace
        cls._policy = policy

        logger.info(
            "FrameworkFilesystem initialized: root=%s virtual_mode=%s",
            resolved_workspace,
            virtual_mode,
        )

        return cls._instance

    @classmethod
    def get(cls) -> FilesystemBackend:
        """Get the singleton filesystem backend.

        Returns:
            FilesystemBackend instance.

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
