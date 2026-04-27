"""Configuration loading utilities (IG-174 Phase 3)."""

import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from soothe_cli.config.cli_config import CLI_CONFIG_FILE, CLIConfig

logger = logging.getLogger(__name__)

# Config cache for performance
_config_cache: dict[str, CLIConfig] = {}


def load_config(config_path: str | None = None) -> CLIConfig:
    """Load CLI client configuration from ``cli_config.yml`` only.

    Client settings (WebSocket endpoint, progress verbosity, etc.) always come from
    :data:`~soothe_cli.config.cli_config.CLI_CONFIG_FILE`. The optional ``config_path``
    argument is accepted for compatibility with existing ``--config`` flags
    but is **ignored**; a warning is logged when it is non-``None``.

    Args:
        config_path: Deprecated. If set, ignored after logging a warning.

    Returns:
        A ``CLIConfig`` instance.
    """
    # Load environment variables from .env file
    # This ensures LangSmith and other env vars are available
    load_dotenv()

    if config_path is not None:
        logger.warning(
            "Ignoring --config %s; CLI client settings are loaded only from %s",
            config_path,
            CLI_CONFIG_FILE,
        )

    cache_key = str(CLI_CONFIG_FILE)

    # Check cache first
    if cache_key in _config_cache:
        logger.debug("Config loaded from cache: %s", cache_key)
        return _config_cache[cache_key]

    load_start = time.perf_counter()

    config = CLIConfig.from_config_file(CLI_CONFIG_FILE)
    _config_cache[cache_key] = config

    elapsed_ms = (time.perf_counter() - load_start) * 1000
    if Path(CLI_CONFIG_FILE).is_file():
        logger.info("Loaded CLI config from '%s' in %.1fms", CLI_CONFIG_FILE, elapsed_ms)
    else:
        logger.debug(
            "CLI config file missing at %s; using defaults (%.1fms)",
            CLI_CONFIG_FILE,
            elapsed_ms,
        )

    return config
