"""Extra skill directory parsing from env vars and cli.yml."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_config_yaml_skills_dirs() -> list[str] | None:
    """Read `[skills].extra_allowed_dirs` from `SOOTHE_HOME/config/cli.yml`.

    Returns:
        List of path strings, or `None` if the key is absent or the file
            cannot be read.
    """
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
    """Merge extra skill directories from env var and cli.yml.

    Extra skills directories extend the containment allowlist used by
    `load_skill_content` to validate that a resolved skill path lives inside a
    trusted root. They do **not** add new skill discovery locations — skills are
    still discovered only from the standard directories. This exists so that
    symlinks inside standard skill directories can legitimately point to targets
    in user-specified locations without being rejected by the path
    containment check.

    The env var (`SOOTHE_EXTRA_SKILLS_DIRS`, colon-separated) takes
    precedence: when set, `cli.yml` values are ignored.

    Args:
        env_raw: Value of `SOOTHE_EXTRA_SKILLS_DIRS` (colon-separated), or
            `None` if unset.
        config_yaml_dirs: List of path strings from
            `[skills].extra_allowed_dirs` in `SOOTHE_HOME/config/cli.yml`.

    Returns:
        List of resolved `Path` objects, or `None` if not configured.
    """
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
