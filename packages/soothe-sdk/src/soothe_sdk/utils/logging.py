"""Shared logging utilities for SDK and CLI packages.

Logging utilities used by both daemon and CLI are provided in SDK to avoid
CLI importing daemon runtime.

This module is part of Phase 1 of IG-174: CLI import violations fix.
"""

import json
import logging
import os
import time
from datetime import UTC
from pathlib import Path
from typing import Any

# Valid values for SOOTHE_LOG_LEVEL (same names as logging module levels).
_SOOTHE_LOG_LEVEL_ENV = "SOOTHE_LOG_LEVEL"
_VALID_STD_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

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


def resolve_cli_log_level(
    *,
    logging_level: str | None = None,
) -> str:
    """Resolve effective log level for the CLI client.

    Precedence:

    #. Environment variable ``SOOTHE_LOG_LEVEL`` (standard level name).
    #. ``logging_level`` from ``cli_config.yml`` when set to a valid level.
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
            "Invalid logging_level %r in cli_config.yml; expected one of %s. Falling back to INFO.",
            logging_level,
            ", ".join(sorted(_VALID_STD_LOG_LEVELS)),
        )

    return "INFO"


class GlobalInputHistory:
    """Global input history manager for CLI.

    Manages persistent history of user inputs across sessions.

    This is a minimal implementation for CLI use. Full implementation
    is in soothe.logging.global_history (daemon-side).
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
        self, text: str, thread_id: str = "default", metadata: dict[str, Any] | None = None
    ) -> None:
        """Add entry to history (CLI-friendly API).

        Args:
            text: Input text to add.
            thread_id: Thread ID for grouping.
            metadata: Optional metadata dict.
        """
        entry = {
            "text": text,
            "thread_id": thread_id,
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


def setup_logging(
    level: str = "INFO", log_file: Path | None = None, format_string: str | None = None
) -> None:
    """Setup logging configuration.

    Configures Python logging for daemon or CLI.

    The console handler (stderr) stays at WARNING so interactive Textual TUI output
    is not corrupted by DEBUG lines. Full ``level`` (including DEBUG from
    ``SOOTHE_LOG_LEVEL``) applies to ``log_file`` when set — tail that file for
    diagnostics.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR) for the root logger and file.
        log_file: Optional log file path (e.g., Path("~/.soothe/logs/soothe-cli.log")).
        format_string: Optional custom format string.
    """
    # Default format
    if not format_string:
        format_string = "%(asctime)s - %(name)s - %(level_short)s - %(message)s"

    level_upper = level.upper()
    root_level = getattr(logging, level_upper)

    # Configure root logger
    logging.basicConfig(level=root_level, format=format_string, handlers=[])

    # Console: WARNING only — DEBUG/INFO must not stream to the terminal during TUI.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ShortLevelFormatter(format_string))
    console_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(console_handler)

    # Add file handler if specified - full log level
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(ShortLevelFormatter(format_string))
        file_handler.setLevel(root_level)
        logging.getLogger().addHandler(file_handler)


__all__ = [
    "GlobalInputHistory",
    "ShortLevelFormatter",
    "abbreviate_logger_name",
    "resolve_cli_log_level",
    "setup_logging",
    "short_level_letter",
]
