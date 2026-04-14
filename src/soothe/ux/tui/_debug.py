"""Debug logging configuration for TUI (stub from deepagents-cli migration).

This module provides debug logging setup for TUI development.
"""

import logging


def configure_debug_logging(logger: logging.Logger | None = None) -> None:
    """Configure detailed debug logging for TUI development.

    Stub implementation - basic logging setup.
    Full implementation should configure detailed formatters,
    file handlers, and TUI-specific debug channels.

    Args:
        logger: Optional logger to configure. If None, configures root logger.
    """
    # Basic debug configuration
    if logger is None:
        logger = logging.getLogger("soothe.ux.tui")

    # Stub - no special configuration
    # Full implementation would set up detailed formatting and handlers
    pass
