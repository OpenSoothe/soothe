"""Secure filesystem backend with path validation and security policy support."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.protocols.policy import PolicyContext, PolicyProtocol


class SecureFilesystemBackend:
    """Wrapper that provides secure path handling and policy enforcement.

    Path resolution strategy:
    1. Relative paths: Treated as virtual paths under root_dir
    2. Absolute paths under root_dir: Use directly after validation
    3. Absolute paths outside root_dir: Require policy approval
    """

    def __init__(
        self,
        backend: Any,
        root_dir: str | Path,
        policy: PolicyProtocol | None = None,
        policy_context: PolicyContext | None = None,
        *,
        allow_outside_root: bool = False,
    ) -> None:
        """Initialize the secure filesystem backend.

        Args:
            backend: The underlying FilesystemBackend to wrap.
            root_dir: Root directory for path validation.
            policy: Optional security policy for access control.
            policy_context: Optional policy context for permission checks.
            allow_outside_root: Allow access outside root_dir without policy check.
        """
        self._backend = backend
        self._root = Path(root_dir).resolve()
        self._policy = policy
        self._policy_context = policy_context
        self._allow_outside_root = allow_outside_root

    def _resolve_and_validate_path(self, file_path: str, operation: str) -> Path:
        """Resolve path with security validation.

        Args:
            file_path: Input file path (relative or absolute)
            operation: Operation type ("read", "write", "edit")

        Returns:
            Resolved absolute path

        Raises:
            ValueError: If path is invalid or outside root without permission
        """
        path = Path(file_path)

        # Case 1: Relative path - resolve under root_dir (virtual path behavior)
        if not path.is_absolute():
            resolved = (self._root / path).resolve()
        else:
            # Case 2 & 3: Absolute path
            resolved = path.resolve()

            # Check if it's under root_dir
            try:
                resolved.relative_to(self._root)
                # Under root - allow without policy check
            except ValueError:
                # Outside root - check policy or config
                if not self._allow_outside_root:
                    if self._policy and self._policy_context:
                        # Check with security policy
                        from soothe.protocols.policy import ActionRequest

                        action = ActionRequest(
                            action_type="tool_call",
                            tool_name=f"fs_{operation}",
                            tool_args={"file_path": str(resolved)},
                        )
                        decision = self._policy.check(action, self._policy_context)
                        if decision.verdict == "deny":
                            msg = (
                                f"Access denied: Path '{resolved}' is outside workspace root. Reason: {decision.reason}"
                            )
                            raise ValueError(msg) from None
                        # "allow" or "need_approval" - proceed (approval handled by middleware)
                    else:
                        # No policy configured - deny by default
                        msg = (
                            f"Path '{resolved}' is outside workspace root '{self._root}'. "
                            "To access paths outside workspace, configure security policy "
                            "or set allow_outside_root=True"
                        )
                        raise ValueError(msg) from None

        return resolved

    def _normalize_for_backend(self, file_path: str, operation: str) -> str:
        """Normalize path before passing to backend.

        Converts absolute paths under root to relative paths to work around
        virtual_mode bug in FilesystemBackend.
        """
        resolved = self._resolve_and_validate_path(file_path, operation)

        # If path is under root, convert to relative path
        try:
            relative = resolved.relative_to(self._root)
            return str(relative)
        except ValueError:
            # Path is outside root - pass as-is (already validated)
            return str(resolved)

    def write(self, file_path: str, content: str) -> Any:
        """Write content to a file with path validation.

        Args:
            file_path: Path to write to (relative or absolute).
            content: Content to write.

        Raises:
            ValueError: If path is outside workspace without permission.
        """
        normalized = self._normalize_for_backend(file_path, "write")
        return self._backend.write(normalized, content)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> Any:
        """Read content from a file with path validation.

        Args:
            file_path: Path to read from (relative or absolute).
            offset: Line offset to start reading.
            limit: Maximum number of lines to read.

        Returns:
            File content.

        Raises:
            ValueError: If path is outside workspace without permission.
        """
        normalized = self._normalize_for_backend(file_path, "read")
        return self._backend.read(normalized, offset, limit)

    def edit(self, file_path: str, old_string: str, new_string: str, *, replace_all: bool = False) -> Any:
        """Edit a file with path validation.

        Args:
            file_path: Path to edit (relative or absolute).
            old_string: String to replace.
            new_string: Replacement string.
            replace_all: Replace all occurrences.

        Raises:
            ValueError: If path is outside workspace without permission.
        """
        normalized = self._normalize_for_backend(file_path, "edit")
        return self._backend.edit(normalized, old_string, new_string, replace_all)

    # Delegate other methods to wrapped backend
    def __getattr__(self, name: str) -> Any:
        """Delegate unknown methods to wrapped backend."""
        return getattr(self._backend, name)
