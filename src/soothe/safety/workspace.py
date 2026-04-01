"""Workspace resolution and validation utilities."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

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
        logger.info("Using SOOTHE_WORKSPACE: %s", workspace)
        return workspace

    # Priority 2: $SOOTHE_HOME/Workspace/ (only when config is default ".")
    soothe_workspace = Path(SOOTHE_HOME) / "Workspace"
    if config_workspace_dir == ".":
        # Create if doesn't exist
        soothe_workspace.mkdir(parents=True, exist_ok=True)
        logger.info("Using default workspace: %s", soothe_workspace)
        return soothe_workspace.resolve()

    # Priority 3: config.yml workspace_dir (legacy)
    workspace = Path(config_workspace_dir).expanduser().resolve()
    _validate_workspace_dir(workspace)
    logger.info("Using config workspace_dir: %s", workspace)
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
        msg = (
            f"Invalid workspace: {path} is a system directory. "
            f"Set SOOTHE_WORKSPACE env var or workspace_dir in config.yml."
        )
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


# ---------------------------------------------------------------------------
# Git Status Collection (RFC-104)
# ---------------------------------------------------------------------------


def _run_git_command(args: list[str], cwd: str, timeout: float = 2.0) -> str:
    """Run a git command with timeout.

    Args:
        args: Git command arguments (e.g., ["branch", "--show-current"]).
        cwd: Working directory to run the command in.
        timeout: Maximum execution time in seconds.

    Returns:
        Command stdout stripped of trailing whitespace, or empty string on failure.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


async def get_git_status(workspace: Path) -> dict[str, Any] | None:
    """Collect git repository status for workspace.

    Runs git commands asynchronously with timeout. Returns None if not a
    git repository or git is unavailable.

    Args:
        workspace: Workspace directory to check.

    Returns:
        Dict with keys: branch, main_branch, status, recent_commits.
        None if not a git repository.
    """
    if not (workspace / ".git").exists():
        return None

    cwd = str(workspace)

    try:
        # Run git commands concurrently via asyncio.to_thread
        branch_future = asyncio.to_thread(_run_git_command, ["branch", "--show-current"], cwd)
        main_ref_future = asyncio.to_thread(_run_git_command, ["symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
        status_future = asyncio.to_thread(_run_git_command, ["status", "--short"], cwd)
        commits_future = asyncio.to_thread(_run_git_command, ["log", "--oneline", "-n", "5"], cwd)

        branch, main_ref, status, commits = await asyncio.gather(
            branch_future, main_ref_future, status_future, commits_future
        )

        # Parse main branch from symbolic-ref output
        # Output format: refs/remotes/origin/main
        main_branch = "main"
        if main_ref and "refs/remotes/origin/" in main_ref:
            main_branch = main_ref.split("/")[-1]

        # Truncate git status to max 20 lines
        status_lines = [line for line in status.split("\n")[:20] if line.strip()]
        truncated_status = "\n".join(status_lines)
    except Exception:
        logger.debug("Git status collection failed for %s", workspace, exc_info=True)
        return None
    else:
        return {
            "branch": branch or "unknown",
            "main_branch": main_branch,
            "status": truncated_status,
            "recent_commits": commits,
        }
