"""Config directory and template path resolution for setup."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from soothe_sdk.paths import SOOTHE_HOME

TEMPLATE_NAMES = ("nano.yml", "soothe.yml", "daemon.yml")


def default_config_dir() -> Path:
    """Return ``$SOOTHE_HOME/config`` (does not create it)."""
    return Path(SOOTHE_HOME).expanduser() / "config"


def resolve_config_dir(config_dir: str | Path | None = None) -> Path:
    """Resolve the target config directory."""
    if config_dir is None:
        return default_config_dir()
    return Path(config_dir).expanduser().resolve()


def config_paths(config_dir: Path) -> dict[str, Path]:
    """Map logical names to paths under *config_dir*."""
    return {
        "nano": config_dir / "nano.yml",
        "soothe": config_dir / "soothe.yml",
        "daemon": config_dir / "daemon.yml",
    }


def monorepo_template_path(name: str) -> Path | None:
    """Return monorepo ``config/<stem>.template.yml`` if present."""
    if name not in TEMPLATE_NAMES:
        return None
    stem = name.removesuffix(".yml")
    candidate = _monorepo_config_dir() / f"{stem}.template.yml"
    return candidate if candidate.is_file() else None


def packaged_template_path(name: str) -> Path | None:
    """Return on-disk path to a packaged template when available (editable installs)."""
    if name not in TEMPLATE_NAMES:
        return None
    here = Path(__file__).resolve().parent / "templates" / name
    return here if here.is_file() else None


def read_template_text(name: str) -> str:
    """Read template contents as UTF-8 text.

    Lookup order:
    1. Package resources (``soothe_daemon.setup.templates``)
    2. On-disk package ``templates/`` directory
    3. Monorepo ``config/<stem>.template.yml``

    Raises:
        FileNotFoundError: If no template can be found.
    """
    if name not in TEMPLATE_NAMES:
        raise FileNotFoundError(f"unknown template name: {name}")

    try:
        root = importlib.resources.files("soothe_daemon.setup.templates")
        return root.joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, TypeError, FileNotFoundError, OSError):
        pass

    packaged = packaged_template_path(name)
    if packaged is not None:
        return packaged.read_text(encoding="utf-8")

    repo = monorepo_template_path(name)
    if repo is not None:
        return repo.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"setup template '{name}' not found in package resources or monorepo config/"
    )


def _monorepo_config_dir() -> Path:
    """Best-effort path to the repo ``config/`` directory."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config"
        if (candidate / "nano.template.yml").is_file():
            return candidate
    return here.parents[5] / "config"
