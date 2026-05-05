"""Workspace resolution and validation utilities."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from soothe_sdk.utils import INVALID_WORKSPACE_DIRS

logger = logging.getLogger(__name__)

_LOOP_ID_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,256}$")


def resolve_loop_daemon_workspace(loop_id: str) -> Path:
    """Resolve per-loop daemon workspace under ``$SOOTHE_HOME/Workspace/<loop_id>/``.

    Used when an AgentLoop owns execution across threads so filesystem tools
    default to an isolated directory instead of the global daemon workspace
    (IG-300).

    Args:
        loop_id: Agent loop identifier (UUID-style string).

    Returns:
        Absolute path to the loop workspace directory (created if missing).

    Raises:
        ValueError: If *loop_id* is empty or contains unsafe characters, or the
            resolved directory is invalid (see ``INVALID_WORKSPACE_DIRS``).
    """
    from soothe.config import SOOTHE_HOME

    text = str(loop_id).strip()
    if not text:
        msg = "loop_id must be non-empty"
        raise ValueError(msg)
    if not _LOOP_ID_SAFE.match(text) or ".." in text or "/" in text or "\\" in text:
        msg = f"Invalid loop_id for workspace directory: {loop_id!r}"
        raise ValueError(msg)

    root = (Path(SOOTHE_HOME) / "Workspace" / text).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _validate_workspace_dir(root)
    return root


def resolve_daemon_workspace(config_workspace_dir: str = "") -> Path:
    """Resolve daemon workspace directory.

    Priority:
    1. ``SOOTHE_WORKSPACE`` environment variable (absolute override).
    2. ``workspace_dir`` from ``SootheConfig`` / YAML. Legacy empty or ``.``
       resolves to ``$SOOTHE_HOME/Workspace`` (IG-327).

    Args:
        config_workspace_dir: ``workspace_dir`` from configuration.

    Returns:
        Resolved absolute workspace path (created if missing, except when
        ``SOOTHE_WORKSPACE`` points at an existing path only).

    Raises:
        ValueError: If resolved workspace is invalid system directory.
    """
    from soothe.config.env import default_soothe_workspace_dir

    env_workspace = os.environ.get("SOOTHE_WORKSPACE")
    if env_workspace:
        workspace = Path(env_workspace).expanduser().resolve()
        _validate_workspace_dir(workspace)
        logger.info("Using SOOTHE_WORKSPACE: %s", workspace)
        return workspace

    text = (config_workspace_dir or "").strip()
    if not text or text == ".":
        workspace = Path(default_soothe_workspace_dir()).expanduser().resolve()
    else:
        workspace = Path(config_workspace_dir).expanduser().resolve()
    _validate_workspace_dir(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info("Using workspace_dir: %s", workspace)
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
        Dict with keys: branch, main_branch, recent_commits (no porcelain ``status``; IG-383).
        None if not a git repository.
    """
    if not (workspace / ".git").exists():
        return None

    cwd = str(workspace)

    try:
        # Run git commands concurrently via asyncio.to_thread (no porcelain status; IG-383)
        branch_future = asyncio.to_thread(_run_git_command, ["branch", "--show-current"], cwd)
        main_ref_future = asyncio.to_thread(
            _run_git_command, ["symbolic-ref", "refs/remotes/origin/HEAD"], cwd
        )
        commits_future = asyncio.to_thread(_run_git_command, ["log", "--oneline", "-n", "5"], cwd)

        branch, main_ref, commits = await asyncio.gather(
            branch_future, main_ref_future, commits_future
        )

        # Parse main branch from symbolic-ref output
        # Output format: refs/remotes/origin/main
        main_branch = "main"
        if main_ref and "refs/remotes/origin/" in main_ref:
            main_branch = main_ref.split("/")[-1]
    except Exception:
        logger.debug("Git status collection failed for %s", workspace, exc_info=True)
        return None
    else:
        return {
            "branch": branch or "unknown",
            "main_branch": main_branch,
            "recent_commits": commits,
        }
