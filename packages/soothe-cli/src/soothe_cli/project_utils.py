"""Utilities for project root detection and project-specific configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_cli._env_vars import SERVER_ENV_PREFIX
from soothe_cli.display.path_utils import path_exists

if TYPE_CHECKING:
    from collections.abc import Mapping

import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectContext:
    """Explicit user/project path context for project-sensitive behavior."""

    user_cwd: Path
    project_root: Path | None = None

    def __post_init__(self) -> None:
        """Validate that path fields are absolute."""
        if not self.user_cwd.is_absolute():
            msg = f"user_cwd must be absolute, got {self.user_cwd!r}"
            raise ValueError(msg)
        if self.project_root is not None and not self.project_root.is_absolute():
            msg = f"project_root must be absolute, got {self.project_root!r}"
            raise ValueError(msg)


def get_server_project_context(
    env: Mapping[str, str] | None = None,
) -> ProjectContext | None:
    """Read the server project context from environment transport data."""
    environment = os.environ if env is None else env
    raw_cwd = environment.get(f"{SERVER_ENV_PREFIX}CWD")
    if not raw_cwd:
        return None

    try:
        user_cwd = Path(raw_cwd).expanduser().resolve()
        raw_project_root = environment.get(f"{SERVER_ENV_PREFIX}PROJECT_ROOT")
        project_root = (
            Path(raw_project_root).expanduser().resolve()
            if raw_project_root
            else find_project_root(user_cwd)
        )
    except OSError:
        logger.warning(
            "Could not resolve server project context from CWD=%s",
            raw_cwd,
            exc_info=True,
        )
        return None

    return ProjectContext(user_cwd=user_cwd, project_root=project_root)


def find_project_root(start_path: str | Path | None = None) -> Path | None:
    """Find the project root by looking for .git directory."""
    current = Path(start_path or Path.cwd()).expanduser().resolve()

    # Walk up the directory tree
    for parent in [current, *list(current.parents)]:
        git_dir = parent / ".git"
        if path_exists(git_dir):
            return parent

    return None
