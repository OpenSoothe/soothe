"""Virtual home directory resolution for virtual mode (IG-405).

In virtual_mode=True, SOOTHE_HOME should be /.soothe (virtual absolute under workspace)
instead of the host-absolute ~/.soothe or $SOOTHE_HOME.

This module provides ContextVars for thread-safe virtual mode state management,
allowing each concurrent execution to have its own virtual home context.
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ContextVar for virtual mode status (set by WorkspaceContextMiddleware)
_current_virtual_mode: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "soothe_virtual_mode", default=False
)

# ContextVar for resolved virtual home path (/.soothe under workspace when virtual)
_virtual_home_path: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "soothe_virtual_home", default=None
)


def set_virtual_mode_context(virtual_mode: bool, workspace: Path) -> None:
    """Set virtual mode context for current async task.

    Called by WorkspaceContextMiddleware to establish thread-specific
    virtual mode and virtual home path.

    Args:
        virtual_mode: Whether virtual mode is enabled.
        workspace: Current workspace path (used to compute virtual home).
    """
    _current_virtual_mode.set(virtual_mode)
    if virtual_mode:
        # In virtual mode, home is /.soothe under the workspace root
        # This is a virtual absolute path that the backend will resolve
        _virtual_home_path.set(workspace / ".soothe")
    else:
        _virtual_home_path.set(None)


def get_virtual_home() -> Path:
    """Get the appropriate home directory for the current context.

    Resolution order:
    1. If virtual mode is enabled and virtual_home is set, return virtual /.soothe
    2. Otherwise, return host SOOTHE_HOME

    Returns:
        Path to use for SOOTHE_HOME-related operations.
    """
    virtual_home = _virtual_home_path.get()
    if virtual_home is not None:
        return virtual_home

    # Fallback to host SOOTHE_HOME
    from soothe.config import SOOTHE_HOME

    return Path(SOOTHE_HOME)


def get_virtual_mode() -> bool:
    """Check if virtual mode is enabled for current context.

    Returns:
        True if virtual mode is active, False otherwise.
    """
    return _current_virtual_mode.get()


def clear_virtual_mode_context() -> None:
    """Clear virtual mode context at stream end.

    Called by WorkspaceContextMiddleware.aafter_agent to cleanup.
    """
    _current_virtual_mode.set(False)
    _virtual_home_path.set(None)


def resolve_virtual_path(relative_path: str) -> Path:
    """Resolve a path relative to virtual home.

    Args:
        relative_path: Path relative to SOOTHE_HOME
            (e.g., "agents/browser/profiles/default").

    Returns:
        Resolved path under virtual home or host SOOTHE_HOME.
    """
    home = get_virtual_home()
    return home / relative_path


def get_virtual_home_relative_path(host_path: Path) -> str | None:
    """Convert a host-absolute path to virtual-home-relative if under virtual home.

    Useful for converting paths like `{workspace}/.soothe/agents/browser/...`
    to `/.soothe/agents/browser/...` for backend operations.

    Args:
        host_path: Host-absolute path to convert.

    Returns:
        Relative path string under virtual home, or None if not under virtual home.
    """
    virtual_home = _virtual_home_path.get()
    if virtual_home is None:
        return None

    try:
        rel = host_path.resolve().relative_to(virtual_home.resolve())
        return f"/.soothe/{rel.as_posix()}"
    except ValueError:
        return None
