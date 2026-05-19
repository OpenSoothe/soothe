"""Logging configuration for Soothe daemon server.

Separate from soothe library's soothe.log — daemon writes to daemon.log
for its own transport, session, and orchestration logs.
"""

from __future__ import annotations

import contextvars
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe.config import SOOTHE_HOME
from soothe_sdk.utils.logging import ShortLevelFormatter

DEFAULT_DAEMON_LOG = "daemon.log"


DEFAULT_MAX_BYTES = 5_242_880  # 5 MB
DEFAULT_BACKUP_COUNT = 3

# Context variables for loop_id and client_id (always log full IDs)
loop_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("loop_id", default=None)
client_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "client_id", default=None
)


class DaemonFormatter(ShortLevelFormatter):
    """Formatter that includes loop_id and client_id from context variables.

    Only includes loop_id and client_id in the prefix when they are actually set,
    keeping logs brief and non-verbose.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format with loop_id and client_id from context variables."""
        loop_id = loop_id_ctx.get()
        client_id = client_id_ctx.get()

        # Build context prefix only when IDs are actually set
        context_parts = []
        if loop_id:
            context_parts.append(f"loop={loop_id}")
        if client_id:
            context_parts.append(f"client={client_id}")

        if context_parts:
            record.context_prefix = "[" + " ".join(context_parts) + "] "
        else:
            record.context_prefix = ""

        return super().format(record)


def set_loop_id(loop_id: str | None) -> None:
    """Set the current loop ID for logging context.

    Args:
        loop_id: The loop ID to set, or None to clear.
    """
    loop_id_ctx.set(loop_id)


def set_client_id(client_id: str | None) -> None:
    """Set the current client ID for logging context.

    Args:
        client_id: The client ID to set, or None to clear.
    """
    client_id_ctx.set(client_id)


def clear_log_context() -> None:
    """Clear both loop_id and client_id from logging context."""
    loop_id_ctx.set(None)
    client_id_ctx.set(None)


def _daemon_log_level_from_soothe_config(cfg: object) -> str:
    """Resolve daemon file log level from ``SootheConfig`` (``debug`` / ``observability``)."""
    if bool(getattr(cfg, "debug", False)):
        return "DEBUG"
    obs = getattr(cfg, "observability", None)
    level = getattr(obs, "log_file_level", None) if obs is not None else None
    if not level:
        logging_view = getattr(cfg, "logging", None)
        file_cfg = getattr(logging_view, "file", None) if logging_view is not None else None
        level = getattr(file_cfg, "level", "INFO") if file_cfg is not None else "INFO"
    return str(level or "INFO").upper()


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
            DaemonFormatter(
                "%(asctime)s %(level_short)s %(name)s:%(lineno)d "
                "%(context_prefix)s%(message)s"
            )
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
                DaemonFormatter(
                    "%(asctime)s %(level_short)s "
                    "%(context_prefix)s%(message)s"
                )
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


__all__ = [
    "DEFAULT_DAEMON_LOG",
    "_daemon_log_level_from_soothe_config",
    "setup_daemon_logging",
]
