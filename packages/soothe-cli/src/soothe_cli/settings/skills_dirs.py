"""Extra skill directory parsing from env vars and cli.yml."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_config_yaml_skills_dirs() -> list[str] | None:
    """Read `[skills].extra_allowed_dirs` from `SOOTHE_HOME/config/cli.yml`."""
    import yaml

    from soothe_cli.model_config import resolve_cli_config_path

    try:
        config_path = resolve_cli_config_path()
        with config_path.open("r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError, yaml.YAMLError):
        logger.warning(
            "Could not read skills config from %s",
            resolve_cli_config_path(),
            exc_info=True,
        )
        return None

    skills_section = data.get("skills", {}) if data else {}
    dirs = skills_section.get("extra_allowed_dirs")
    if isinstance(dirs, list):
        return dirs
    return None


def _parse_extra_skills_dirs(
    env_raw: str | None,
    config_yaml_dirs: list[str] | None = None,
) -> list[Path] | None:
    """Merge extra skill directories from env var and cli.yml."""
    # Env var takes precedence when set
    if env_raw:
        dirs = [Path(p.strip()).expanduser().resolve() for p in env_raw.split(":") if p.strip()]
        return dirs or None

    if config_yaml_dirs:
        dirs = [
            Path(p).expanduser().resolve()
            for p in config_yaml_dirs
            if isinstance(p, str) and p.strip()
        ]
        return dirs or None

    return None
