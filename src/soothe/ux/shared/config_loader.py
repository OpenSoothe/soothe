"""Configuration loading utilities."""

import json
import logging
import sys
import time
from pathlib import Path

import typer
from dotenv import load_dotenv

from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"

# Config cache for performance
_config_cache: dict[str, SootheConfig] = {}


def load_config(config_path: str | None = None) -> SootheConfig:
    """Load SootheConfig from a file path or defaults with caching.

    When no ``config_path`` is provided, automatically checks
    ``~/.soothe/config/config.yml`` and loads it if present.

    Uses an in-memory cache to avoid re-parsing config files.

    Args:
        config_path: Path to a YAML/JSON config file, or ``None`` for defaults.

    Returns:
        A ``SootheConfig`` instance.
    """
    # Load environment variables from .env file
    # This ensures LangSmith and other env vars are available
    load_dotenv()

    # Determine the actual path to use
    if not config_path and _DEFAULT_CONFIG_PATH.is_file():
        config_path = str(_DEFAULT_CONFIG_PATH)

    # Use "default" as cache key when no path is provided
    cache_key = config_path or "default"

    # Check cache first
    if cache_key in _config_cache:
        logger.debug("Config loaded from cache: %s", cache_key)
        return _config_cache[cache_key]

    load_start = time.perf_counter()

    if not config_path:
        config = SootheConfig()
        _config_cache[cache_key] = config
        elapsed_ms = (time.perf_counter() - load_start) * 1000
        logger.debug("Created default config in %.1fms", elapsed_ms)
        return config

    path = Path(config_path)
    with path.open() as f:
        if config_path.endswith(".json"):
            config_data = json.load(f)
        elif config_path.endswith((".yaml", ".yml")):
            try:
                import yaml

                config_data = yaml.safe_load(f)
            except ImportError:
                typer.echo(
                    "Error: PyYAML required for YAML config files. Install: pip install pyyaml",
                    err=True,
                )
                sys.exit(1)
        else:
            typer.echo("Error: Unsupported config format. Use .yaml, .yml, or .json", err=True)
            sys.exit(1)

    config = SootheConfig(**config_data)
    _config_cache[cache_key] = config

    elapsed_ms = (time.perf_counter() - load_start) * 1000
    logger.info("Loaded config from '%s' in %.1fms", config_path, elapsed_ms)

    return config
