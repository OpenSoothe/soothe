"""Shared config loader for Soothe examples."""

from pathlib import Path

from soothe.config import SOOTHE_HOME
from soothe.config.settings import SootheConfig


def _load_nano_or_split(nano_path: Path) -> SootheConfig:
    """Load ``nano.yml``, composing sibling ``soothe.yml`` when present."""
    soothe_sibling = nano_path.parent / "soothe.yml"
    if soothe_sibling.is_file():
        return SootheConfig.from_split_yaml_files(
            nano_path=str(nano_path),
            soothe_path=str(soothe_sibling),
        )
    return SootheConfig.from_yaml_file(str(nano_path))


def load_example_config() -> SootheConfig:
    """Load config from SOOTHE_HOME nano.yml (+ soothe.yml) or develop nano.yml."""
    home_nano = Path(SOOTHE_HOME).expanduser() / "config" / "nano.yml"
    if home_nano.is_file():
        return _load_nano_or_split(home_nano)
    dev_nano = Path(__file__).parent.parent / "config" / "develop" / "nano.yml"
    if dev_nano.is_file():
        return _load_nano_or_split(dev_nano)
    return SootheConfig()
