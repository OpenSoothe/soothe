"""Runtime workspace context and process-level defaults."""

from __future__ import annotations

import logging
import os
import tempfile
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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
    """Set workspace context for current async task."""
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
    """Clear workspace context at stream end."""
    if token is not None:
        try:
            _workspace_context.reset(token)
        except ValueError:
            _workspace_context.set(WorkspaceContext())
    else:
        _workspace_context.set(WorkspaceContext())


def set_virtual_mode_context(virtual_mode: bool, workspace: Path) -> None:
    """Set virtual mode context for current async task."""
    set_workspace_context(workspace=workspace, virtual_mode=virtual_mode)


def get_virtual_home() -> Path:
    """Get the appropriate home directory for the current context."""
    ctx = get_workspace_context()
    if ctx.virtual_home is not None:
        return ctx.virtual_home
    from soothe_nano.config import SOOTHE_HOME

    return Path(SOOTHE_HOME)


def get_virtual_mode() -> bool:
    """Check if virtual mode is enabled for current context."""
    return get_workspace_context().virtual_mode


def clear_virtual_mode_context() -> None:
    """Clear virtual mode context at stream end."""
    reset_workspace_context()


def get_virtual_home_relative_path(host_path: Path) -> str | None:
    """Convert a host-absolute path to virtual-home-relative if under virtual home."""
    ctx = get_workspace_context()
    if ctx.virtual_home is None:
        return None
    try:
        rel = host_path.resolve().relative_to(ctx.virtual_home.resolve())
        return f"/.soothe/{rel.as_posix()}"
    except ValueError:
        return None


def resolve_process_workspace_root() -> Path:
    """Resolve process-default workspace root when no explicit workspace is bound."""
    env_workspace = os.environ.get("SOOTHE_WORKSPACE")
    if env_workspace:
        return Path(env_workspace).expanduser().resolve()
    workspace = Path(tempfile.gettempdir()) / "soothe-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace.resolve()


def resolve_daemon_workspace() -> Path:
    """Resolve daemon fallback workspace (ephemeral TEMP unless overridden)."""
    from soothe_nano.workspace.workspace_policy import _validate_workspace_dir

    env_workspace = os.environ.get("SOOTHE_WORKSPACE")
    if env_workspace:
        workspace = Path(env_workspace).expanduser().resolve()
        _validate_workspace_dir(workspace)
        return workspace
    workspace = Path(tempfile.gettempdir()) / "soothe-daemon-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _validate_workspace_dir(workspace)
    return workspace


def cleanup_anonymous_workspaces() -> None:
    """Clean up anonymous workspace directories (daemon shutdown)."""
    import shutil

    from soothe_nano.config import SOOTHE_HOME
    from soothe_nano.workspace.workspace_policy import normalize_user_id

    cleaned = 0
    for base in ("data/workspaces", "workspaces"):
        workspaces_dir = Path(SOOTHE_HOME) / base
        if not workspaces_dir.exists():
            continue
        anon_tree = workspaces_dir / normalize_user_id(None)
        if anon_tree.is_dir():
            try:
                shutil.rmtree(anon_tree)
                cleaned += 1
            except OSError as e:
                logger.warning("Failed to cleanup %s: %s", anon_tree, e)
        for ws_dir in workspaces_dir.glob("anon_*"):
            if ws_dir.is_dir():
                try:
                    shutil.rmtree(ws_dir)
                    cleaned += 1
                except OSError as e:
                    logger.warning("Failed to cleanup %s: %s", ws_dir, e)
    if cleaned > 0:
        logger.info("Cleaned %d anonymous workspace location(s)", cleaned)
