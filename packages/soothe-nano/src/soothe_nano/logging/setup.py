"""Logging configuration for Soothe."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_sdk.utils.logging import ShortLevelFormatter

from soothe_nano.config import SOOTHE_HOME
from soothe_nano.logging.context import get_thread_id

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

# Community plugins (soothe-plugins) use this logger tree; mirror soothe handlers here.
COMMUNITY_LOGGER_NAME = "soothe_plugins"
PACKAGE_LOGGER_NAMES: tuple[str, ...] = ("soothe", COMMUNITY_LOGGER_NAME)

# Suffix length for conversation thread id in log lines (full id stays in context vars).
_THREAD_ID_LOG_SUFFIX_LEN = 4


def _short_thread_id_for_log(thread_id: str) -> str:
    """Return last N characters of thread id for compact, distinctive log tags."""
    tid = thread_id.strip()
    if not tid:
        return ""
    if len(tid) <= _THREAD_ID_LOG_SUFFIX_LEN:
        return tid
    return tid[-_THREAD_ID_LOG_SUFFIX_LEN:]


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


def _package_loggers() -> tuple[logging.Logger, ...]:
    """Return package loggers that receive shared Soothe file/console handlers."""
    return tuple(logging.getLogger(name) for name in PACKAGE_LOGGER_NAMES)


def _rotating_handler_path(handler: RotatingFileHandler) -> Path | None:
    """Resolve a rotating handler target path, or ``None`` if unavailable."""
    base = getattr(handler, "baseFilename", None)
    if base is None:
        return None
    try:
        return Path(str(base)).resolve()
    except OSError:
        return None


def _has_rotating_file_handler_at(logger: logging.Logger, log_path: Path) -> bool:
    """Return whether ``logger`` already has a rotating handler for ``log_path``."""
    resolved = log_path.resolve()
    return any(
        isinstance(handler, RotatingFileHandler) and _rotating_handler_path(handler) == resolved
        for handler in logger.handlers
    )


def _add_rotating_file_handler(
    loggers: tuple[logging.Logger, ...],
    *,
    log_file: str,
    file_level: int,
    max_bytes: int,
    backup_count: int,
) -> None:
    """Attach a rotating file handler to each logger that lacks one for ``log_file``."""
    log_path = Path(log_file).resolve()
    formatter = ThreadFormatter(
        "%(asctime)s %(level_short)s %(thread_id)s %(name)s:%(lineno)d %(message)s"
    )
    for logger in loggers:
        if _has_rotating_file_handler_at(logger, log_path):
            continue
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(file_level)
        logger.addHandler(file_handler)


def _add_console_handler_if_missing(
    loggers: tuple[logging.Logger, ...],
    *,
    stream: object,
    console_level: int,
    console_format: str,
) -> None:
    """Attach a console stream handler to each logger that lacks one for ``stream``."""
    for logger in loggers:
        if any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
            and handler.stream == stream
            for handler in logger.handlers
        ):
            continue
        console_handler = logging.StreamHandler(stream)  # type: ignore[arg-type]
        console_handler.setFormatter(ShortLevelFormatter(console_format))
        console_handler.setLevel(console_level)
        logger.addHandler(console_handler)


def setup_logging(
    config: SootheConfig | None = None,
    *,
    foreground: bool = False,
    log_file: str | Path | None = None,
) -> None:
    """Configure Soothe and community package loggers with file and optional console handlers.

    Writes to ``SOOTHE_HOME/logs/soothe.log`` (rotating, 5 MB max, 3 backups) for both
    ``soothe.*`` and ``soothe_plugins.*`` loggers unless ``log_file`` overrides the path.
    Optionally outputs to console when enabled in config.

    Args:
        config: Optional config to read logging configuration from.
        foreground: When ``True``, forces console logging to stdout at INFO level
            regardless of config settings. Useful for foreground process mode.
        log_file: Optional log file path override (default ``SOOTHE_HOME/logs/soothe.log``).
    """
    from soothe_nano.config import SootheConfig as _SootheConfig

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

    package_loggers = _package_loggers()
    min_level = min(file_level, console_level)
    for logger in package_loggers:
        logger.setLevel(min_level)

    resolved_log_file = (
        str(log_file)
        if log_file is not None
        else (cfg.logging.file.path or str(log_dir / "soothe.log"))
    )
    _add_rotating_file_handler(
        package_loggers,
        log_file=resolved_log_file,
        file_level=file_level,
        max_bytes=cfg.logging.file.max_bytes,
        backup_count=cfg.logging.file.backup_count,
    )

    console_enabled = cfg.logging.console.enabled or foreground
    if console_enabled:
        console_stream = (
            sys.stderr
            if foreground
            else (sys.stderr if cfg.logging.console.stream == "stderr" else sys.stdout)
        )
        _add_console_handler_if_missing(
            package_loggers,
            stream=console_stream,
            console_level=console_level,
            console_format=cfg.logging.console.format,
        )

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
        "langfuse",
        "browser_use",
        "bubus",
        "cdp_use",
        "websockets",
        "requests",
    )
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)
