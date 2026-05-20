"""CLI file logging for ``~/.soothe/logs/cli.log`` (rotating, 5 MB, 3 backups)."""

from __future__ import annotations

import logging
from pathlib import Path

from soothe_sdk.utils.logging import setup_logging as _setup_sdk_logging

# High-volume routing / step-card traces belong at DEBUG only.
_QUIET_AT_INFO = (
    "soothe_cli.runtime.state.step_router",
    "soothe.ux.tui.trace",
)


def setup_logging(level: str, *, log_file: Path | None = None) -> None:
    """Configure CLI logging (SDK file handler; stderr stays WARNING).

    At ``INFO``, routing and optional TUI trace loggers are capped at ``WARNING``
    so ``cli.log`` stays readable. Set ``SOOTHE_LOG_LEVEL=DEBUG`` for full traces.
    """
    _setup_sdk_logging(level, log_file=log_file)
    if level.upper() == "INFO":
        for name in _QUIET_AT_INFO:
            logging.getLogger(name).setLevel(logging.WARNING)
