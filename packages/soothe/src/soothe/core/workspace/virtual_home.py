"""Virtual home directory resolution for virtual mode.

In virtual_mode=True, SOOTHE_HOME should be /.soothe (virtual absolute under workspace)
instead of the host-absolute ~/.soothe or $SOOTHE_HOME.

Delegates to ``WorkspaceContext`` (single ContextVar) for thread-safe
virtual mode state management.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def set_virtual_mode_context(virtual_mode: bool, workspace: Path) -> None:
    """Set virtual mode context for current async task.

    Called by WorkspaceContextMiddleware to establish thread-specific
    virtual mode and virtual home path.

    Args:
        virtual_mode: Whether virtual mode is enabled.
        workspace: Current workspace path (used to compute virtual home).
    """
    from soothe.core.workspace.context import set_workspace_context

    set_workspace_context(workspace=workspace, virtual_mode=virtual_mode)


def get_virtual_home() -> Path:
    """Get the appropriate home directory for the current context.

    Resolution order:
    1. If virtual mode is enabled and virtual_home is set, return virtual /.soothe
    2. Otherwise, return host SOOTHE_HOME

    Returns:
        Path to use for SOOTHE_HOME-related operations.
    """
    from soothe.core.workspace.context import get_workspace_context

    ctx = get_workspace_context()
    if ctx.virtual_home is not None:
        return ctx.virtual_home

    # Fallback to host SOOTHE_HOME
    from soothe.config import SOOTHE_HOME

    return Path(SOOTHE_HOME)


def get_virtual_mode() -> bool:
    """Check if virtual mode is enabled for current context.

    Returns:
        True if virtual mode is active, False otherwise.
    """
    from soothe.core.workspace.context import get_workspace_context

    return get_workspace_context().virtual_mode


def clear_virtual_mode_context() -> None:
    """Clear virtual mode context at stream end.

    Called by WorkspaceContextMiddleware.aafter_agent to cleanup.
    """
    from soothe.core.workspace.context import reset_workspace_context

    reset_workspace_context()


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

    Useful for converting paths like ``{workspace}/.soothe/agents/browser/...``
    to ``/.soothe/agents/browser/...`` for backend operations.

    Args:
        host_path: Host-absolute path to convert.

    Returns:
        Relative path string under virtual home, or None if not under virtual home.
    """
    from soothe.core.workspace.context import get_workspace_context

    ctx = get_workspace_context()
    if ctx.virtual_home is None:
        return None

    try:
        rel = host_path.resolve().relative_to(ctx.virtual_home.resolve())
        return f"/.soothe/{rel.as_posix()}"
    except ValueError:
        return None
