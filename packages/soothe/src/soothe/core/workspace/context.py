"""Unified workspace context (single ContextVar replacing three separate ones).

Consolidates workspace path, virtual mode, and virtual home into one
``WorkspaceContext`` dataclass stored in a single ``ContextVar``.  The
middleware sets/clears one object instead of coordinating across
``framework_filesystem.py`` and ``virtual_home.py``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_DEFAULT = None  # sentinel for unset


@dataclass
class WorkspaceContext:
    """Per-async-task workspace state."""

    workspace: Path | None = None
    virtual_mode: bool = False
    virtual_home: Path | None = None


_workspace_context: ContextVar[WorkspaceContext] = ContextVar(
    "soothe_workspace_context",
    default=WorkspaceContext(),
)


def set_workspace_context(
    *,
    workspace: Path | str | None = None,
    virtual_mode: bool = False,
) -> Token[WorkspaceContext]:
    """Set workspace context for current async task.

    Called by ``WorkspaceContextMiddleware`` at stream start.  Returns a
    ``Token`` that can be passed to ``reset_workspace_context`` for safe
    restoration.
    """
    ws_path = Path(workspace) if isinstance(workspace, str) else workspace
    virtual_home = ws_path / ".soothe" if virtual_mode and ws_path else None

    ctx = WorkspaceContext(
        workspace=ws_path,
        virtual_mode=virtual_mode,
        virtual_home=virtual_home,
    )
    return _workspace_context.set(ctx)


def get_workspace_context() -> WorkspaceContext:
    """Get workspace context for current async task."""
    return _workspace_context.get()


def reset_workspace_context(token: Token[WorkspaceContext] | None = None) -> None:
    """Clear workspace context at stream end.

    Called by ``WorkspaceContextMiddleware`` to prevent context leaks
    across stream boundaries.
    """
    if token is not None:
        try:
            _workspace_context.reset(token)
        except ValueError:
            # Token came from a different asyncio Context. Clear directly.
            _workspace_context.set(WorkspaceContext())
    else:
        _workspace_context.set(WorkspaceContext())
