"""Workspace resolution and validation utilities."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from soothe_sdk.utils import INVALID_WORKSPACE_DIRS

logger = logging.getLogger(__name__)


def resolve_daemon_workspace() -> Path:
    """Resolve daemon fallback workspace (ephemeral TEMP unless overridden).

    Priority:
    1. ``SOOTHE_WORKSPACE`` environment variable (absolute override).
    2. TEMP directory (ephemeral, not persisted across restarts).

    The daemon workspace is only used as a fallback when no user workspace
    can be resolved (anonymous users without client_workspace).

    Returns:
        Resolved absolute workspace path.

    Raises:
        ValueError: If resolved workspace is invalid system directory.
    """
    env_workspace = os.environ.get("SOOTHE_WORKSPACE")
    if env_workspace:
        workspace = Path(env_workspace).expanduser().resolve()
        _validate_workspace_dir(workspace)
        logger.info("Using SOOTHE_WORKSPACE: %s", workspace)
        return workspace

    # Ephemeral TEMP fallback
    workspace = Path(tempfile.gettempdir()) / "soothe-daemon-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _validate_workspace_dir(workspace)
    logger.info("Using ephemeral daemon workspace: %s", workspace)
    return workspace


def cleanup_anonymous_workspaces() -> None:
    """Clean up anonymous workspace directories (daemon shutdown).

    Removes ``$SOOTHE_HOME/data/workspaces/anonymous/`` and legacy flat ``anon_*`` dirs.
    Also cleans up old ``$SOOTHE_HOME/workspaces/anonymous/`` if it exists (pre-migration).
    """
    import shutil

    from soothe.config import SOOTHE_HOME
    from soothe.foundation.workspace.loop_workspace import normalize_user_id

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
                logger.info("Cleaned anonymous workspace tree: %s", anon_tree)
            except OSError as e:
                logger.warning("Failed to cleanup %s: %s", anon_tree, e)

        for ws_dir in workspaces_dir.glob("anon_*"):
            if ws_dir.is_dir():
                try:
                    shutil.rmtree(ws_dir)
                    cleaned += 1
                    logger.info("Cleaned legacy anonymous workspace: %s", ws_dir)
                except OSError as e:
                    logger.warning("Failed to cleanup %s: %s", ws_dir, e)

    if cleaned > 0:
        logger.info("Cleaned %d anonymous workspace location(s)", cleaned)


def _validate_workspace_dir(path: Path) -> None:
    """Validate workspace is not a system directory.

    Args:
        path: Workspace path to validate.

    Raises:
        ValueError: If path is invalid system directory.
    """
    path_str = str(path.resolve())

    if path_str in INVALID_WORKSPACE_DIRS:
        msg = f"Invalid workspace: {path} is a system directory. Set SOOTHE_WORKSPACE env var."
        raise ValueError(msg)


def validate_client_workspace(workspace: str | Path) -> Path:
    """Validate and resolve client-provided workspace.

    Args:
        workspace: Client workspace path (from cwd).

    Returns:
        Resolved absolute workspace path.

    Raises:
        ValueError: If workspace is invalid.
    """
    original_path = Path(workspace)
    path = original_path.expanduser().resolve()

    # Reject system directories (check both original and resolved paths)
    # This handles symlinks like /home -> /System/Volumes/Data/home on macOS
    original_str = str(original_path)
    resolved_str = str(path)

    if original_str in INVALID_WORKSPACE_DIRS or resolved_str in INVALID_WORKSPACE_DIRS:
        msg = f"Invalid client workspace: {workspace} is a system directory. Please run from a project directory."
        raise ValueError(msg)

    # Warn if workspace doesn't exist
    if not path.exists():
        logger.warning("Client workspace does not exist: %s", path)

    return path


def translate_client_path_to_container(
    client_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a client-side path to its container-side equivalent (RFC-621).

    When host_root/container_root are not configured, returns the path unchanged.
    Raises ValueError if client_path is not under host_root.

    Args:
        client_path: Path on the host/client machine.
        host_root: Parent directory on the host that is volume-mounted.
        container_root: Mount point inside the container.

    Returns:
        Translated path for use inside the container.

    Raises:
        ValueError: If client_path is not under host_root when mapping is configured.
    """
    if not host_root or not container_root:
        return Path(client_path).resolve()

    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(client_path).resolve()

    try:
        relative = resolved.relative_to(host)
    except ValueError:
        msg = (
            f"Client workspace {resolved} is not under configured "
            f"host_root {host}. All workspaces must reside under the "
            f"configured host_root for container deployments."
        )
        raise ValueError(msg) from None

    return container / relative


def translate_container_path_to_client(
    container_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a container-side path to its client-side equivalent (RFC-621).

    When host_root/container_root are not configured, returns the path unchanged.
    If the path is not under container_root, returns it unchanged.

    Args:
        container_path: Path inside the container.
        host_root: Parent directory on the host that is volume-mounted.
        container_root: Mount point inside the container.

    Returns:
        Translated path for display on the client machine.
    """
    if not host_root or not container_root:
        return Path(container_path).resolve()

    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(container_path).resolve()

    try:
        relative = resolved.relative_to(container)
    except ValueError:
        return resolved

    return host / relative
