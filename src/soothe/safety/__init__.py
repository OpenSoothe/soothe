"""Safety policy and workspace security implementations."""

from soothe.safety.config_driven import ConfigDrivenPolicy
from soothe.safety.types import INVALID_WORKSPACE_DIRS
from soothe.safety.workspace import (
    resolve_daemon_workspace,
    validate_client_workspace,
)

__all__ = [
    "INVALID_WORKSPACE_DIRS",
    "ConfigDrivenPolicy",
    "FrameworkFilesystem",
    "resolve_daemon_workspace",
    "validate_client_workspace",
]


# Lazy import for FrameworkFilesystem to avoid circular dependencies
def __getattr__(name: str):
    if name == "FrameworkFilesystem":
        from soothe.safety.filesystem import FrameworkFilesystem

        return FrameworkFilesystem
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
