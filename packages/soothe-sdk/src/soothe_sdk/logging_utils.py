"""Shared logging utilities for SDK and CLI packages.

Logging utilities used by both daemon and CLI are provided in SDK to avoid
CLI importing daemon runtime.

This module is part of Phase 1 of IG-174: CLI import violations fix.
"""

import json
import logging
from pathlib import Path
from typing import Any


class GlobalInputHistory:
    """Global input history manager for CLI.

    Manages persistent history of user inputs across sessions.

    This is a minimal implementation for CLI use. Full implementation
    is in soothe.logging.global_history (daemon-side).
    """

    def __init__(self, history_file: Path):
        """Initialize global history manager.

        Args:
            history_file: Path to history JSONL file.
        """
        self.history_file = history_file
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

    def append(self, entry: dict[str, Any]) -> None:
        """Append entry to history.

        Args:
            entry: History entry to append.
        """
        self._history.append(entry)
        self._save()

    def _save(self) -> None:
        """Save history to file."""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w") as f:
                for entry in self._history:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logging.warning(f"Failed to save history: {e}")


def setup_logging(level: str = "INFO", log_file: Path = None, format_string: str = None) -> None:
    """Setup logging configuration.

    Configures Python logging for daemon or CLI.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional log file path.
        format_string: Optional custom format string.
    """
    # Default format
    if not format_string:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(level=getattr(logging, level.upper()), format=format_string, handlers=[])

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_string))
    logging.getLogger().addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format_string))
        logging.getLogger().addHandler(file_handler)


__all__ = [
    "GlobalInputHistory",
    "setup_logging",
]
