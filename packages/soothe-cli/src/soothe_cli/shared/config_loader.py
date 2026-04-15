"""Configuration loading utilities (IG-174 Phase 3)."""

import logging
import time
from pathlib import Path

from dotenv import load_dotenv
from soothe_sdk import SOOTHE_HOME

from soothe_cli.config.cli_config import CLIConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config.yml"

# Config cache for performance
_config_cache: dict[str, CLIConfig] = {}


def load_config(config_path: str | None = None) -> CLIConfig:
    """Load CLIConfig from a file path or defaults with caching.

    CLIConfig is minimal and designed for independent CLI package installation.
    Full daemon config available via WebSocket RPC when needed.

    When no ``config_path`` is provided, automatically checks
    ``~/.soothe/config.yml`` and loads it if present.

    Uses an in-memory cache to avoid re-parsing config files.

    Args:
        config_path: Path to a YAML config file, or ``None`` for defaults.

    Returns:
        A ``CLIConfig`` instance.
    """
    # Load environment variables from .env file
    # This ensures LangSmith and other env vars are available
    load_dotenv()

    # Determine the actual path to use
    path_to_load: Path | None = None
    if config_path:
        path_to_load = Path(config_path)
    elif _DEFAULT_CONFIG_PATH.is_file():
        path_to_load = _DEFAULT_CONFIG_PATH

    # Use "default" as cache key when no path is provided
    cache_key = str(path_to_load) if path_to_load else "default"

    # Check cache first
    if cache_key in _config_cache:
        logger.debug("Config loaded from cache: %s", cache_key)
        return _config_cache[cache_key]

    load_start = time.perf_counter()

    # Load minimal CLI config
    config = CLIConfig.from_config_file(path_to_load)
    _config_cache[cache_key] = config

    elapsed_ms = (time.perf_counter() - load_start) * 1000
    if path_to_load:
        logger.info("Loaded CLI config from '%s' in %.1fms", path_to_load, elapsed_ms)
    else:
        logger.debug("Created default CLI config in %.1fms", elapsed_ms)

    return config
