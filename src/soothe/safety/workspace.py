"""Workspace resolution and validation utilities."""

import logging
import os
from pathlib import Path

from soothe.safety.types import INVALID_WORKSPACE_DIRS

logger = logging.getLogger(__name__)


def resolve_daemon_workspace(config_workspace_dir: str = ".") -> Path:
    """Resolve daemon's default workspace with priority order.

    Priority:
    1. SOOTHE_WORKSPACE env var
    2. $SOOTHE_HOME/Workspace/ (default)
    3. workspace_dir from config.yml (legacy)

    Args:
        config_workspace_dir: workspace_dir from SootheConfig.

    Returns:
        Resolved absolute workspace path.

    Raises:
        ValueError: If resolved workspace is invalid system directory.
    """
    from soothe.config import SOOTHE_HOME

    # Priority 1: SOOTHE_WORKSPACE env var
    env_workspace = os.environ.get("SOOTHE_WORKSPACE")
    if env_workspace:
        workspace = Path(env_workspace).expanduser().resolve()
        _validate_workspace_dir(workspace)
        logger.info(f"Using SOOTHE_WORKSPACE: {workspace}")
        return workspace

    # Priority 2: $SOOTHE_HOME/Workspace/ (only when config is default ".")
    soothe_workspace = Path(SOOTHE_HOME) / "Workspace"
    if config_workspace_dir == ".":
        # Create if doesn't exist
        soothe_workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using default workspace: {soothe_workspace}")
        return soothe_workspace.resolve()

    # Priority 3: config.yml workspace_dir (legacy)
    workspace = Path(config_workspace_dir).expanduser().resolve()
    _validate_workspace_dir(workspace)
    logger.info(f"Using config workspace_dir: {workspace}")
    return workspace


def _validate_workspace_dir(path: Path) -> None:
    """Validate workspace is not a system directory.

    Args:
        path: Workspace path to validate.

    Raises:
        ValueError: If path is invalid system directory.
    """
    path_str = str(path.resolve())

    if path_str in INVALID_WORKSPACE_DIRS:
        raise ValueError(
            f"Invalid workspace: {path} is a system directory. "
            f"Set SOOTHE_WORKSPACE env var or workspace_dir in config.yml."
        )


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
        raise ValueError(
            f"Invalid client workspace: {workspace} is a system directory. Please run from a project directory."
        )

    # Warn if workspace doesn't exist
    if not path.exists():
        logger.warning(f"Client workspace does not exist: {path}")

    return path
