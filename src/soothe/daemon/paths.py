"""Path utilities for Soothe daemon."""

from pathlib import Path

from soothe.config import SOOTHE_HOME

_PID_FILENAME = "soothe.pid"


def _soothe_dir() -> Path:
    """Return the canonical Soothe home directory."""
    return Path(SOOTHE_HOME).expanduser()


def pid_path() -> Path:
    """Return the canonical PID file path."""
    return _soothe_dir() / _PID_FILENAME
