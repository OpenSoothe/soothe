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

# Third-party per-frame wire traces (``< TEXT ...``) flood ``cli.log`` at DEBUG.
_QUIET_ALWAYS = (
    "websockets",
    "websockets.client",
)


def setup_logging(level: str, *, log_file: Path | None = None) -> None:
    """Configure CLI logging (SDK file handler; stderr stays WARNING).

    At ``INFO``, routing and optional TUI trace loggers are capped at ``WARNING``
    so ``cli.log`` stays readable. The ``websockets`` library is always capped at
    ``WARNING`` so frame-level wire logs never appear even when
    ``SOOTHE_LOG_LEVEL=DEBUG``. Set ``SOOTHE_LOG_LEVEL=DEBUG`` for full app traces.
    """
    _setup_sdk_logging(level, log_file=log_file)
    for name in _QUIET_ALWAYS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if level.upper() == "INFO":
        for name in _QUIET_AT_INFO:
            logging.getLogger(name).setLevel(logging.WARNING)
