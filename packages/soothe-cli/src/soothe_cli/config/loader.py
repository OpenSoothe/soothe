"""Configuration loading utilities (IG-174 Phase 3)."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from soothe_cli.config.cli_config import CLIConfig

logger = logging.getLogger(__name__)

_runtime_config: ContextVar[CLIConfig | None] = ContextVar(
    "soothe_cli_runtime_config", default=None
)


def set_runtime_config(config: CLIConfig) -> None:
    """Install CLI config parsed from global CLI flags."""
    _runtime_config.set(config)


def reset_runtime_config() -> None:
    """Clear runtime config (mainly for tests)."""
    _runtime_config.set(None)


def load_config() -> CLIConfig:
    """Return active CLI config from parsed global flags, or defaults.

    Returns:
        A ``CLIConfig`` instance.
    """
    cfg = _runtime_config.get()
    if cfg is not None:
        logger.debug("Using CLI config from parsed global flags")
        return cfg

    logger.debug("Using default CLI config (no global flags parsed)")
    return CLIConfig()
