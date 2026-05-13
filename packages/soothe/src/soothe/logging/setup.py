"""Logging configuration for Soothe."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_sdk.utils.logging import ShortLevelFormatter

from soothe.config import SOOTHE_HOME
from soothe.logging.context import get_thread_id

if TYPE_CHECKING:
    from soothe.config import SootheConfig

# Prefix length for conversation thread id in log lines (full id stays in context vars).
_THREAD_ID_LOG_PREFIX_LEN = 4


def _short_thread_id_for_log(thread_id: str) -> str:
    """Return first N characters of thread id for compact log tags."""
    tid = thread_id.strip()
    if not tid:
        return ""
    return tid[:_THREAD_ID_LOG_PREFIX_LEN]


class ThreadFormatter(ShortLevelFormatter):
    """Custom formatter that includes a short Soothe conversation thread id tag."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with a short conversation thread id prefix.

        Args:
            record: The log record to format.

        Returns:
            The formatted log message string.
        """
        soothe_thread_id = get_thread_id()
        if soothe_thread_id:
            short = _short_thread_id_for_log(soothe_thread_id)
            record.thread_id = f"[{short}]" if short else "[main]"
        else:
            record.thread_id = "[main]"
        return super().format(record)


def setup_logging(config: SootheConfig | None = None, *, foreground: bool = False) -> None:
    """Configure the ``soothe`` logger hierarchy with file and optional console handlers.

    Writes to ``SOOTHE_HOME/logs/soothe.log`` (rotating, 5 MB max, 3 backups).
    Optionally outputs to console when enabled in config.

    Args:
        config: Optional config to read logging configuration from.
        foreground: When ``True``, forces console logging to stdout at INFO level
            regardless of config settings. Useful for foreground process mode.
    """
    from soothe.config import SootheConfig as _SootheConfig

    cfg = config or _SootheConfig()
    log_dir = Path(SOOTHE_HOME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    file_level_name = cfg.logging.file.level.upper()
    console_level_name = cfg.logging.console.level.upper()

    if cfg.debug:
        file_level_name = "DEBUG"
        console_level_name = "DEBUG"
    elif foreground:
        console_level_name = "INFO"

    file_level = getattr(logging, file_level_name, logging.INFO)
    console_level = getattr(logging, console_level_name, logging.WARNING)

    root_logger = logging.getLogger("soothe")
    root_logger.setLevel(min(file_level, console_level))

    log_file = cfg.logging.file.path or str(log_dir / "soothe.log")
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=cfg.logging.file.max_bytes,
            backupCount=cfg.logging.file.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            ThreadFormatter(
                "%(asctime)s %(level_short)s %(thread_id)s %(name)s:%(lineno)d %(message)s"
            )
        )
        file_handler.setLevel(file_level)
        root_logger.addHandler(file_handler)

    console_enabled = cfg.logging.console.enabled or foreground
    console_stream = (
        sys.stderr
        if foreground
        else (sys.stderr if cfg.logging.console.stream == "stderr" else sys.stdout)
    )
    if console_enabled:
        if not any(
            isinstance(h, logging.StreamHandler) and h.stream == console_stream
            for h in root_logger.handlers
        ):
            console_handler = logging.StreamHandler(console_stream)
            console_handler.setFormatter(ShortLevelFormatter(cfg.logging.console.format))
            console_handler.setLevel(console_level)
            root_logger.addHandler(console_handler)

    _suppress_noisy_third_party()


def _suppress_noisy_third_party() -> None:
    """Suppress noisy third-party loggers to WARNING level."""
    noisy = (
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
        "langchain_core",
        "langgraph",
        "langsmith",
        "browser_use",
        "bubus",
        "cdp_use",
        "websockets",
        "requests",
    )
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)
