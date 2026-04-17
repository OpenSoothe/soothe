"""Shared logging utilities for SDK and CLI packages.

Logging utilities used by both daemon and CLI are provided in SDK to avoid
CLI importing daemon runtime.

This module is part of Phase 1 of IG-174: CLI import violations fix.
"""

import json
import logging
from pathlib import Path
from typing import Any, Literal

# Verbosity to log level mapping
VERBOSITY_TO_LOG_LEVEL: dict[Literal["quiet", "minimal", "normal", "detailed", "debug"], str] = {
    "quiet": "WARNING",
    "minimal": "INFO",
    "normal": "INFO",
    "detailed": "DEBUG",
    "debug": "DEBUG",
}
"""Map verbosity levels to Python logging levels.

Used by CLI commands to convert user-facing verbosity to log level.
"""


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
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


def setup_logging(
    level: str = "INFO", log_file: Path | None = None, format_string: str | None = None
) -> None:
    """Setup logging configuration.

    Configures Python logging for daemon or CLI.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR) for file logging.
        log_file: Optional log file path (e.g., Path("~/.soothe/logs/soothe-cli.log")).
        format_string: Optional custom format string.
    """
    # Default format
    if not format_string:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(level=getattr(logging, level.upper()), format=format_string, handlers=[])

    # Add console handler - WARNING level only to reduce noise
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_string))
    console_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(console_handler)

    # Add file handler if specified - full log level
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format_string))
        file_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(file_handler)


__all__ = [
    "GlobalInputHistory",
    "VERBOSITY_TO_LOG_LEVEL",
    "setup_logging",
]
