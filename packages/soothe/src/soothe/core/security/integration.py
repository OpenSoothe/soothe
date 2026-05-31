"""Integration utilities for security layer with workspace backend.

This module provides wrappers and mixins to integrate PathValidator
and SecurityEnforcer with the existing filesystem backend.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from .enforcement import SecurityEnforcer, SecurityError
from .policy import PolicyAction, PolicyDecision, SecurityPolicy
from .validator import PathValidationError, PathValidator, ValidationResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.backends.filesystem import FilesystemBackend

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class SecureFilesystemWrapper:
    """Wrapper that adds security validation to any FilesystemBackend.

    This wrapper intercepts all path-based operations and validates them
    against security policies before delegating to the underlying backend.

    Example:
        >>> from deepagents.backends.filesystem import FilesystemBackend
        >>> backend = FilesystemBackend("/workspace")
        >>> secure_backend = SecureFilesystemWrapper(
        ...     backend,
        ...     workspace="/workspace",
        ...     policy=STRICT_POLICY,
        ... )
        >>> # All operations are now validated
        >>> secure_backend.read("../etc/passwd")  # Raises SecurityError
    """

    # Operations that require path validation
    PATH_OPERATIONS = frozenset({
        "read", "aread",
        "write", "awrite",
        "edit", "aedit",
        "delete", "adelete",
        "ls", "als",
        "ls_info", "als_info",
        "glob", "aglob",
        "grep", "agrep",
        "grep_raw", "agrep_raw",
        "exists", "aexists",
        "mkdir", "amkdir",
        "download_files", "adownload_files",
    })

    # Operations that take path as first argument
    PATH_FIRST_ARG = frozenset({
        "read", "aread",
        "write", "awrite",
        "edit", "aedit",
        "delete", "adelete",
        "ls", "als",
        "ls_info", "als_info",
        "glob", "aglob",
        "exists", "aexists",
        "mkdir", "amkdir",
    })

    def __init__(
        self,
        backend: FilesystemBackend,
        workspace: Path | str,
        policy: SecurityPolicy | None = None,
        enforcer: SecurityEnforcer | None = None,
        block_on_violation: bool = True,
    ) -> None:
        """Initialize secure wrapper.

        Args:
            backend: The underlying filesystem backend.
            workspace: Base workspace directory.
            policy: Security policy (ignored if enforcer provided).
            enforcer: Pre-configured security enforcer.
            block_on_violation: Whether to raise on policy violations.
        """
        self._backend = backend
        self._workspace = Path(workspace).resolve()
        self._block_on_violation = block_on_violation

        if enforcer:
            self._enforcer = enforcer
        else:
            self._enforcer = SecurityEnforcer(
                workspace=self._workspace,
                policy=policy,
            )

        logger.info(
            "SecureFilesystemWrapper initialized: workspace=%s, policy=%s",
            self._workspace,
            self._enforcer.policy.name,
        )

    def _validate_path(
        self,
        path: str,
        operation: str,
    ) -> PolicyDecision:
        """Validate path and return decision."""
        return self._enforcer.check_access(path, operation)

    def _check_and_normalize(
        self,
        path: str,
        operation: str,
    ) -> str:
        """Check access and return normalized path.

        Raises:
            SecurityError: If access is denied and block_on_violation is True.
        """
        decision = self._validate_path(path, operation)

        if decision.is_denied and self._block_on_violation:
            raise SecurityError(
                f"Access denied for {operation} on '{path}': {decision.reason}",
                decision=decision,
            )

        # Return sanitized path
        return self._enforcer.validator.sanitize(path)

    def __getattr__(self, name: str) -> Any:
        """Delegate to backend with security wrapping."""
        attr = getattr(self._backend, name)

        if name in self.PATH_OPERATIONS and callable(attr):
            return self._wrap_operation(name, attr)

        return attr

    def _wrap_operation(
        self,
        operation: str,
        func: Callable[..., Any],
    ) -> Callable[..., Any]:
        """Wrap an operation with security validation."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract path from args or kwargs
            path = self._extract_path(operation, args, kwargs)

            if path is not None:
                # Validate the path
                normalized = self._check_and_normalize(path, operation)

                # Replace path in args/kwargs
                args, kwargs = self._replace_path(
                    operation, args, kwargs, normalized,
                )

            return func(*args, **kwargs)

        return wrapper

    def _extract_path(
        self,
        operation: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> str | None:
        """Extract path from operation arguments."""
        # Check kwargs first
        if "path" in kwargs:
            return kwargs["path"]

        # Check first positional arg for path-first operations
        if operation in self.PATH_FIRST_ARG and args:
            return args[0]

        # Special cases
        if operation in ("download_files", "adownload_files"):
            if "paths" in kwargs:
                return kwargs["paths"][0] if kwargs["paths"] else None
            if args:
                return args[0][0] if args[0] else None

        return None

    def _replace_path(
        self,
        operation: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        new_path: str,
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Replace path in arguments with normalized version."""
        if "path" in kwargs:
            kwargs["path"] = new_path
            return args, kwargs

        if operation in self.PATH_FIRST_ARG and args:
            return (new_path,) + args[1:], kwargs

        if operation in ("download_files", "adownload_files"):
            if "paths" in kwargs:
                kwargs["paths"] = [new_path]
            elif args:
                args = ([new_path],) + args[1:]

        return args, kwargs

    @property
    def backend(self) -> FilesystemBackend:
        """Get underlying backend."""
        return self._backend

    @property
    def enforcer(self) -> SecurityEnforcer:
        """Get security enforcer."""
        return self._enforcer

    def get_stats(self) -> dict[str, Any]:
        """Get security statistics."""
        return self._enforcer.get_stats()


class SecurityMixin:
    """Mixin class to add security validation to filesystem backends.

    This mixin can be added to any class that implements filesystem operations
    to automatically add security validation.

    Example:
        >>> class MyBackend(FilesystemBackend, SecurityMixin):
        ...     def __init__(self, workspace):
        ...         super().__init__(workspace)
        ...         self._init_security(workspace)
        ...
        ...     def read(self, path):
        ...         self._secure_path(path, "read")  # Validates before reading
        ...         return super().read(path)
    """

    def _init_security(
        self,
        workspace: Path | str,
        policy: SecurityPolicy | None = None,
    ) -> None:
        """Initialize security for this mixin."""
        self._security_enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=policy,
        )
        self._security_enabled = True

    def _secure_path(self, path: str, operation: str) -> str:
        """Validate path and return normalized version.

        Raises:
            SecurityError: If access is denied.
        """
        if not self._security_enabled:
            return path

        return self._security_enforcer.get_safe_path(path, operation)

    def _check_access(self, path: str, operation: str) -> PolicyDecision:
        """Check if operation is allowed without raising."""
        if not self._security_enabled:
            return PolicyDecision(allowed=True, action=PolicyAction.ALLOW)

        return self._security_enforcer.check_access(path, operation)

    def _disable_security(self) -> None:
        """Disable security checks (use with caution)."""
        self._security_enabled = False

    def _enable_security(self) -> None:
        """Enable security checks."""
        self._security_enabled = True

    @property
    def security_stats(self) -> dict[str, Any]:
        """Get security statistics."""
        if hasattr(self, "_security_enforcer"):
            return self._security_enforcer.get_stats()
        return {}


def secure_operation(
    operation: str | None = None,
    path_arg: str = "path",
    policy: SecurityPolicy | None = None,
) -> Callable[[F], F]:
    """Decorator to add security validation to a function.

    Args:
        operation: Operation type (defaults to function name).
        path_arg: Name of the path argument.
        policy: Optional policy override.

    Example:
        >>> @secure_operation("read")
        ... def read_file(path: str) -> str:
        ...     return open(path).read()
    """

    def decorator(func: F) -> F:
        op_name = operation or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get workspace from function or module
            workspace = _get_workspace_from_context(func)

            if workspace is None:
                raise RuntimeError(
                    f"Cannot secure {op_name}: no workspace configured",
                )

            # Extract path
            path = kwargs.get(path_arg)
            if path is None and args:
                # Try to get from positional args
                import inspect
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if path_arg in params:
                    idx = params.index(path_arg)
                    if idx < len(args):
                        path = args[idx]

            if path is None:
                raise ValueError(f"Path argument '{path_arg}' not found")

            # Validate
            enforcer = SecurityEnforcer(workspace=workspace, policy=policy)
            decision = enforcer.check_access(path, op_name)

            if decision.is_denied:
                raise SecurityError(
                    f"Access denied for {op_name} on '{path}': {decision.reason}",
                    decision=decision,
                )

            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def _get_workspace_from_context(func: Callable[..., Any]) -> Path | None:
    """Try to get workspace from function or its module."""
    # Try function attribute
    if hasattr(func, "_security_workspace"):
        return Path(func._security_workspace)

    # Try module
    import inspect
    module = inspect.getmodule(func)
    if module and hasattr(module, "SECURITY_WORKSPACE"):
        return Path(module.SECURITY_WORKSPACE)

    # Try calling module's get_workspace
    if module and hasattr(module, "get_workspace"):
        try:
            return Path(module.get_workspace())
        except Exception:
            pass

    return None


def patch_backend_security(
    backend_class: type,
    policy: SecurityPolicy | None = None,
) -> type:
    """Monkey-patch a backend class with security validation.

    Args:
        backend_class: The class to patch.
        policy: Security policy to apply.

    Returns:
        The patched class.
    """
    original_init = backend_class.__init__

    def secure_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)

        # Initialize security after backend init
        workspace = getattr(self, "cwd", None) or getattr(self, "root_dir", None)
        if workspace:
            self._security_enforcer = SecurityEnforcer(
                workspace=workspace,
                policy=policy,
            )
            self._security_enabled = True

    backend_class.__init__ = secure_init  # type: ignore[method-assign]

    # Wrap path-based methods
    path_methods = [
        "read", "write", "edit", "delete",
        "ls", "ls_info", "glob", "grep",
        "exists", "mkdir",
    ]

    for method_name in path_methods:
        if hasattr(backend_class, method_name):
            original = getattr(backend_class, method_name)

            @functools.wraps(original)
            def secure_method(
                self: Any,
                path: str,
                *args: Any,
                **kwargs: Any,
            ) -> Any:
                if getattr(self, "_security_enabled", False):
                    enforcer = getattr(self, "_security_enforcer", None)
                    if enforcer:
                        decision = enforcer.check_access(path, method_name)
                        if decision.is_denied:
                            raise SecurityError(
                                f"Access denied: {decision.reason}",
                                decision=decision,
                            )

                return original(self, path, *args, **kwargs)

            setattr(backend_class, method_name, secure_method)

    return backend_class


def create_secure_backend(
    backend: FilesystemBackend,
    workspace: Path | str,
    policy: SecurityPolicy | None = None,
) -> SecureFilesystemWrapper:
    """Create a secure wrapper around a filesystem backend.

    This is a convenience function for creating a SecureFilesystemWrapper.

    Args:
        backend: The filesystem backend to wrap.
        workspace: Base workspace directory.
        policy: Security policy to apply.

    Returns:
        SecureFilesystemWrapper instance.
    """
    return SecureFilesystemWrapper(
        backend=backend,
        workspace=workspace,
        policy=policy,
    )
