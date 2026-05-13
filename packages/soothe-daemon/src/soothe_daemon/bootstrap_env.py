"""Load ``.env`` before YAML parsing so ``${VAR}`` placeholders resolve (providers, Langfuse)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _soothe_home_dir() -> Path:
    return Path(os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))).expanduser()


def bootstrap_dotenv() -> None:
    """Load env files early: walk from cwd, then ``$SOOTHE_HOME/.env`` (detached daemon cwd)."""
    load_dotenv()
    home_env = _soothe_home_dir() / ".env"
    if home_env.is_file():
        load_dotenv(home_env, override=False)


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
