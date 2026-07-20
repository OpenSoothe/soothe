"""Self-contained config loader for soothe-nano examples."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config import SOOTHE_HOME, SootheConfig


def load_nano_example_config() -> SootheConfig:
    """Load config from ``SOOTHE_HOME`` or repo ``config/develop/config.yml``."""
    home_config = Path(SOOTHE_HOME).expanduser() / "config" / "config.yml"
    if home_config.is_file():
        return SootheConfig.from_yaml_file(str(home_config))

    repo_root = Path(__file__).resolve().parents[5]
    dev_config = repo_root / "config" / "develop" / "config.yml"
    if dev_config.is_file():
        return SootheConfig.from_yaml_file(str(dev_config))

    return SootheConfig()
