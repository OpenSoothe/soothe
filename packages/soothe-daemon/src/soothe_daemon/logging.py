"""Logging configuration for Soothe daemon server.

Separate from soothe library's soothe.log — daemon writes to daemon.log
for its own transport, session, and orchestration logs.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe.config import SOOTHE_HOME
from soothe_sdk.utils.logging import ShortLevelFormatter

DEFAULT_DAEMON_LOG = "daemon.log"
DEFAULT_MAX_BYTES = 5_242_880  # 5 MB
DEFAULT_BACKUP_COUNT = 3


def setup_daemon_logging(
    level: str = "INFO",
    log_file: str | None = None,
    foreground: bool = False,
) -> None:
    """Configure the ``soothe_daemon`` logger hierarchy.

    Writes to ``SOOTHE_HOME/logs/daemon.log`` (rotating, 5 MB max, 3 backups).
    Separate from soothe library's ``soothe.log``.

    Args:
        level: Log level for file output (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional custom log file path.
        foreground: When True, also logs to stdout at INFO level.
    """
    log_dir = Path(SOOTHE_HOME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    file_level = getattr(logging, level.upper(), logging.INFO)

    # Daemon logger (soothe_daemon.*)
    daemon_logger = logging.getLogger("soothe_daemon")
    daemon_logger.setLevel(file_level)

    actual_log_file = log_file or str(log_dir / DEFAULT_DAEMON_LOG)
    if not any(isinstance(h, RotatingFileHandler) for h in daemon_logger.handlers):
        file_handler = RotatingFileHandler(
            actual_log_file,
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            ShortLevelFormatter("%(asctime)s %(level_short)s %(name)s:%(lineno)d %(message)s")
        )
        file_handler.setLevel(file_level)
        daemon_logger.addHandler(file_handler)

    # Console output for foreground mode
    if foreground:
        import sys

        if not any(
            isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            for h in daemon_logger.handlers
        ):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(
                ShortLevelFormatter("%(asctime)s %(level_short)s %(message)s")
            )
            console_handler.setLevel(logging.INFO)
            daemon_logger.addHandler(console_handler)

    _suppress_daemon_noisy_loggers()


def _suppress_daemon_noisy_loggers() -> None:
    """Suppress noisy third-party loggers used by daemon components."""
    noisy = (
        "websockets",
        "aiohttp",
        "uvicorn",
        "httpx",
        "httpcore",
    )
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)


__all__ = ["setup_daemon_logging", "DEFAULT_DAEMON_LOG"]
