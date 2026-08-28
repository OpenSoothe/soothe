"""LangGraph stream config construction with version and workspace metadata."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_cli._version import __version__

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

config: RunnableConfig = {
    "recursion_limit": 1000,
}
"""Default LangGraph runnable config.

Sets `recursion_limit` to 1000 to accommodate deeply nested agent graphs without
hitting the default LangGraph ceiling.
"""

_git_branch_cache: dict[str, str | None] = {}
"""Per-cwd cache of resolved git branch names.

Avoids repeated `git rev-parse` subprocess calls within the same session. Keyed
by `str(Path.cwd())`; `None` values indicate the directory is not inside a git
repository.
"""


def _get_git_branch() -> str | None:
    """Return the current git branch name, or `None` if not in a repo."""
    import subprocess  # noqa: S404

    try:
        cwd = str(Path.cwd())
    except OSError:
        logger.debug("Could not determine cwd for git branch lookup", exc_info=True)
        return None
    if cwd in _git_branch_cache:
        return _git_branch_cache[cwd]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            branch = result.stdout.strip() or None
            _git_branch_cache[cwd] = branch
            return branch
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        logger.debug("Could not determine git branch", exc_info=True)
    _git_branch_cache[cwd] = None
    return None


def build_stream_config(
    loop_id: str,
    assistant_id: str | None,
    *,
    sandbox_type: str | None = None,
    workspace: str | None = None,
) -> RunnableConfig:
    """Build the LangGraph stream config dict.

    Injects the resolved Soothe version into `metadata["versions"]` so runs
    can be correlated with specific releases. The runtime config replaces the
    graph config's `versions` key at stream time, so this must carry the
    canonical release string.

    Args:
    loop_id: Active StrangeLoop id (stored under LangGraph `configurable.thread_id`).
    assistant_id: The agent/assistant identifier, if any.
    sandbox_type: Sandbox provider name for trace metadata, or `None` if no
    sandbox is active.
    workspace: Workspace directory for in-process TUI runs. When
    omitted, uses `Path.cwd()` (resolved). Mirrored to
    `configurable["workspace"]` for middleware and task-tool propagation.

    Returns:
    Config dict with `configurable` and `metadata` keys.
    """
    from datetime import UTC, datetime

    try:
        cwd = str(Path.cwd())
    except OSError:
        logger.warning("Could not determine working directory", exc_info=True)
        cwd = ""

    metadata: dict[str, Any] = {
        "versions": {"Soothe": __version__},
    }
    from soothe_cli._env_vars import USER_ID

    user_id = os.environ.get(USER_ID)
    if user_id:
        metadata["user_id"] = user_id
    if cwd:
        metadata["cwd"] = cwd
    if assistant_id:
        metadata.update(
            {
                "assistant_id": assistant_id,
                "agent_name": assistant_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    branch = _get_git_branch()
    if branch:
        metadata["git_branch"] = branch
    if sandbox_type and sandbox_type != "none":
        metadata["sandbox_type"] = sandbox_type

    configurable: dict[str, Any] = {"thread_id": loop_id}
    resolved_workspace: str | None = None
    if workspace and str(workspace).strip():
        try:
            resolved_workspace = str(Path(workspace).expanduser().resolve())
        except OSError:
            logger.warning(
                "Could not resolve workspace path %r; omitting configurable.workspace",
                workspace,
                exc_info=True,
            )
    else:
        try:
            resolved_workspace = str(Path.cwd().resolve())
        except OSError:
            logger.warning("Could not resolve cwd for configurable.workspace", exc_info=True)
    if resolved_workspace:
        configurable["workspace"] = resolved_workspace

    return {
        "configurable": configurable,
        "metadata": metadata,
    }
