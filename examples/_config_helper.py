"""Shared config loader for Soothe examples."""

from pathlib import Path

from soothe import SootheConfig
from soothe.config import SOOTHE_HOME


def load_example_config() -> SootheConfig:
    """Load config from SOOTHE_HOME or fall back to config/config.dev.yml."""
    home_config = Path(SOOTHE_HOME).expanduser() / "config" / "config.yml"
    if home_config.is_file():
        return SootheConfig.from_yaml_file(str(home_config))
    dev_config = Path(__file__).parent.parent / "config" / "config.dev.yml"
    if dev_config.is_file():
        return SootheConfig.from_yaml_file(str(dev_config))
    return SootheConfig()
