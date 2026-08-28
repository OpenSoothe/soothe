"""Safe pathlib probes for TUI code that must not crash on invalid paths."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def path_exists(path: Path) -> bool:
    """Return whether `path` exists, treating OS errors as non-existent."""
    try:
        return path.exists()
    except OSError as exc:
        logger.debug("path_exists failed for %s: %s", path, exc)
        return False


def path_is_file(path: Path) -> bool:
    """Return whether `path` is a file, treating OS errors as false."""
    try:
        return path.is_file()
    except OSError as exc:
        logger.debug("path_is_file failed for %s: %s", path, exc)
        return False


def path_is_dir(path: Path) -> bool:
    """Return whether `path` is a directory, treating OS errors as false."""
    try:
        return path.is_dir()
    except OSError as exc:
        logger.debug("path_is_dir failed for %s: %s", path, exc)
        return False
