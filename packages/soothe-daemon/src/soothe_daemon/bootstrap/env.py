"""Load ``.env`` before YAML parsing so ``${VAR}`` placeholders resolve (providers, Langfuse)."""

from __future__ import annotations

import os
from pathlib import Path

import soothe_sdk._upstream_warnings as _upstream_warnings  # noqa: F401
from dotenv import load_dotenv

_INVOCATION_DIR_ENV_VARS = ("SOOTHE_DAEMON_INVOCATION_DIR", "SOOTHE_CLI_WORKSPACE")


def _soothe_home_dir() -> Path:
    return Path(os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))).expanduser()


def _find_dotenv_from_path(start_path: Path) -> Path | None:
    """Find the nearest ``.env`` file walking up from *start_path*."""
    current = start_path.expanduser().resolve()
    for parent in [current, *list(current.parents)]:
        candidate = parent / ".env"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _dotenv_start_path() -> Path:
    """Directory to search for a project ``.env`` (invocation dir or cwd)."""
    for name in _INVOCATION_DIR_ENV_VARS:
        raw = os.environ.get(name, "").strip()
        if raw:
            return Path(raw).expanduser()
    return Path.cwd()


def bootstrap_dotenv(*, start_path: Path | str | None = None) -> bool:
    """Load project and global ``.env`` files before config/YAML parsing.

    Precedence (``override=False`` throughout; shell exports win):

    1. Nearest project ``.env`` from *start_path*, invocation env, or cwd
    2. ``$SOOTHE_HOME/.env`` global defaults

    Args:
        start_path: Optional directory to begin the upward ``.env`` search.

    Returns:
        ``True`` when at least one dotenv file was loaded.
    """
    loaded = False
    search_root = Path(start_path).expanduser() if start_path is not None else _dotenv_start_path()
    project_env = _find_dotenv_from_path(search_root)
    if project_env is not None:
        loaded = load_dotenv(project_env, override=False) or loaded

    home_env = _soothe_home_dir() / ".env"
    if home_env.is_file():
        loaded = load_dotenv(home_env, override=False) or loaded

    return loaded


def load_dotenv_adjacent_to_yaml(*yaml_paths: str | Path | None) -> None:
    """Load ``.env`` next to any existing YAML file path (e.g. repo ``config/`` + root ``.env``)."""
    seen: set[Path] = set()
    for raw in yaml_paths:
        if raw is None:
            continue
        path = Path(raw).expanduser()
        if not path.is_file():
            continue
        candidate = (path.parent / ".env").resolve()
        if candidate.is_file() and candidate not in seen:
            load_dotenv(candidate, override=False)
            seen.add(candidate)
