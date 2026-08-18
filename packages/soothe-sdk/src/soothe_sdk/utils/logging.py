"""Shared logging utilities for SDK and CLI packages.

Logging utilities used by both the SDK and CLI are provided in the SDK to
avoid the CLI importing host runtime.
"""

import json
import logging
import os
import random
import time
from datetime import UTC
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Shared rotation policy for ``~/.soothe/logs/{soothe,cli}.log``.
DEFAULT_LOG_MAX_BYTES = 5_242_880  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 3

# Valid values for SOOTHE_LOG_LEVEL (same names as logging module levels).
_SOOTHE_LOG_LEVEL_ENV = "SOOTHE_LOG_LEVEL"
_VALID_STD_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Client ID for CLI session (8 hex chars, generated once per process)
_CLI_CLIENT_ID: str = random.randbytes(4).hex()

# Single-letter markers for compact log lines (use %(level_short)s in format strings).
_LEVEL_SHORT_BY_NO: dict[int, str] = {
    logging.DEBUG: "D",
    logging.INFO: "I",
    logging.WARNING: "W",
    logging.ERROR: "E",
    logging.CRITICAL: "C",
}


def short_level_letter(levelno: int) -> str:
    """Return one-letter code for a logging level number."""
    return _LEVEL_SHORT_BY_NO.get(levelno, "?")


def abbreviate_logger_name(name: str) -> str:
    """Shorten a dotted logger path by abbreviating all but the last two segments.

    Each earlier segment becomes its first character (e.g. ``soothe`` → ``s``).
    The last two segments stay unchanged so package/module context stays readable.

    Args:
        name: Logger name, typically ``__name__`` with dots.

    Returns:
        Compact form, or ``name`` unchanged when fewer than three segments.
    """
    if not name:
        return name
    parts = name.split(".")
    if len(parts) <= 2:
        return name
    head: list[str] = []
    for p in parts[:-2]:
        head.append(p[0] if p else "?")
    return ".".join(head + parts[-2:])


class ShortLevelFormatter(logging.Formatter):
    """Formatter that supplies ``level_short`` and compact ``%(asctime)s`` timestamps.

    Timestamps use ``YYYYMMDDTHHMMSS.mmm`` (local time, same ``converter`` as the
    standard formatter). This preserves full calendar date, wall-clock time, and
    millisecond resolution while shortening the default
    ``YYYY-MM-DD HH:MM:SS,mmm`` form.

    If ``datefmt`` is set on the formatter, that format is used instead (via
    ``super()``).
    """

    def formatTime(  # noqa: N802 — matches ``logging.Formatter.formatTime``
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """Format ``record.created`` as compact local time with milliseconds."""
        if datefmt:
            return super().formatTime(record, datefmt)
        ct = self.converter(record.created)
        stamp = time.strftime("%Y%m%dT%H%M%S", ct)
        # ``LogRecord.msecs`` is usually int but may be float on some versions/paths.
        ms = int(round(float(record.msecs))) % 1000
        return f"{stamp}.{ms:03d}"

    def format(self, record: logging.LogRecord) -> str:
        record.level_short = short_level_letter(record.levelno)
        saved_name = record.name
        record.name = abbreviate_logger_name(saved_name)
        try:
            return super().format(record)
        finally:
            record.name = saved_name


class ClientFormatter(ShortLevelFormatter):
    """Formatter that includes a client ID tag for CLI logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format with client ID tag like ``[Client:be5d8902]``."""
        record.client_id = f"[Client:{_CLI_CLIENT_ID}]"
        try:
            return super().format(record)
        finally:
            delattr(record, "client_id")


def resolve_cli_log_level(
    *,
    logging_level: str | None = None,
) -> str:
    """Resolve effective log level for the CLI client.

    Precedence:

    #. Environment variable ``SOOTHE_LOG_LEVEL`` (standard level name).
    #. ``logging_level`` from ``--log-level`` when set to a valid level.
    #. Default ``INFO``.

    Args:
        logging_level: Optional explicit level from config (``DEBUG``, ``INFO``, …).
            Ignored when ``None`` or not a valid standard level (falls through with a
            warning).

    Returns:
        Log level string suitable for :func:`setup_logging` (e.g. ``DEBUG``).
    """
    env_raw = os.environ.get(_SOOTHE_LOG_LEVEL_ENV, "").strip().upper()
    if env_raw in _VALID_STD_LOG_LEVELS:
        return env_raw

    if logging_level is not None and str(logging_level).strip() != "":
        cfg_raw = str(logging_level).strip().upper()
        if cfg_raw in _VALID_STD_LOG_LEVELS:
            return cfg_raw
        logging.getLogger(__name__).warning(
            "Invalid logging_level %r; expected one of %s. Falling back to INFO.",
            logging_level,
            ", ".join(sorted(_VALID_STD_LOG_LEVELS)),
        )

    return "INFO"


class GlobalInputHistory:
    """Global input history manager for CLI.

    Manages persistent history of user inputs across sessions.

    This is a minimal implementation for CLI use. The full implementation
    lives in the host package.
    """

    def __init__(self, history_file: Path | str):
        """Initialize global history manager.

        Args:
            history_file: Path to history JSONL file.
        """
        self.history_file = Path(history_file)
        self._history: list[dict[str, Any]] = []

    def load(self) -> list[dict[str, Any]]:
        """Load history from file.

        Returns:
            List of history entries.
        """
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file) as f:
                self._history = [json.loads(line) for line in f if line.strip()]
            return self._history
        except Exception as e:
            logging.warning(f"Failed to load history: {e}")
            return []

    def add(
        self, text: str, loop_id: str = "default", metadata: dict[str, Any] | None = None
    ) -> None:
        """Add entry to history (CLI-friendly API).

        Args:
            text: Input text to add.
            loop_id: Client scope for grouping (e.g. active loop or ``\"default\"``).
            metadata: Optional metadata dict.
        """
        entry = {
            "text": text,
            "loop_id": loop_id,
            "timestamp": self._get_timestamp(),
            "metadata": metadata or {},
        }
        self._append_to_file(entry)

    def append(self, entry: dict[str, Any]) -> None:
        """Append entry to history.

        Args:
            entry: History entry to append.
        """
        self._history.append(entry)
        self._save()

    def _append_to_file(self, entry: dict[str, Any]) -> None:
        """Append entry directly to file (concurrent-safe).

        Args:
            entry: History entry to append.
        """
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
            # Also add to in-memory cache
            self._history.append(entry)
        except Exception as e:
            logging.warning(f"Failed to append to history file: {e}")

    def _save(self) -> None:
        """Save history to file."""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w") as f:
                for entry in self._history:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logging.warning(f"Failed to save history: {e}")

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format.

        Returns:
            ISO format timestamp string.
        """
        from datetime import datetime

        return datetime.now(UTC).isoformat()


def _handler_targets_log_file(handler: logging.Handler, log_file: Path) -> bool:
    """True when ``handler`` writes to the same path as ``log_file``."""
    if not isinstance(handler, RotatingFileHandler):
        return False
    base = getattr(handler, "baseFilename", None)
    if base is None:
        return False
    try:
        return os.path.samefile(base, log_file)
    except OSError:
        try:
            return Path(str(base)).resolve() == log_file.resolve()
        except OSError:
            return False


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    format_string: str | None = None,
    *,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
) -> None:
    """Setup logging configuration.

    Configures Python logging for the CLI client (and other lightweight callers).

    The console handler (stderr) stays at WARNING so interactive Textual TUI output
    is not corrupted by DEBUG lines. Full ``level`` (including DEBUG from
    ``SOOTHE_LOG_LEVEL``) applies to ``log_file`` when set — tail that file for
    diagnostics. File output uses :class:`~logging.handlers.RotatingFileHandler`
    (default 5 MB per file, three backups).

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR) for the root logger and file.
        log_file: Optional log file path (e.g., Path("~/.soothe/logs/cli.log")).
        format_string: Optional custom format string.
        max_bytes: Rotate log file after this many bytes (default 5 MB).
        backup_count: Number of rotated backup files to retain.
    """
    # Default format matches soothe.log: timestamp level [Client:xxxxxxxx] name:lineno message
    if not format_string:
        format_string = "%(asctime)s %(level_short)s %(client_id)s %(name)s:%(lineno)d %(message)s"

    level_upper = level.upper()
    root_level = getattr(logging, level_upper)

    # Configure root logger
    logging.basicConfig(level=root_level, format=format_string, handlers=[])

    root_logger = logging.getLogger()
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        existing = next(
            (h for h in root_logger.handlers if _handler_targets_log_file(h, log_file)),
            None,
        )
        if existing is not None:
            existing.setLevel(root_level)
        else:
            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(ClientFormatter(format_string))
            file_handler.setLevel(root_level)
            root_logger.addHandler(file_handler)


__all__ = [
    "ClientFormatter",
    "DEFAULT_LOG_BACKUP_COUNT",
    "DEFAULT_LOG_MAX_BYTES",
    "GlobalInputHistory",
    "ShortLevelFormatter",
    "abbreviate_logger_name",
    "resolve_cli_log_level",
    "setup_logging",
    "short_level_letter",
]
