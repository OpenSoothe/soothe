"""Path utilities for Soothe daemon."""

from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig

_SOCKET_FILENAME = "soothe.sock"
_PID_FILENAME = "soothe.pid"


def _soothe_dir() -> Path:
    """Return the canonical Soothe home directory."""
    return Path(SOOTHE_HOME).expanduser()


def resolve_socket_path(config: SootheConfig | None = None) -> Path:
    """Return the effective Unix socket path for the given config."""
    if config is not None:
        configured = config.daemon.transports.unix_socket.path
        if configured:
            return Path(configured).expanduser()
    return _soothe_dir() / _SOCKET_FILENAME


def socket_path() -> Path:
    """Return the canonical Unix socket path."""
    return resolve_socket_path()


def pid_path() -> Path:
    """Return the canonical PID file path."""
    return _soothe_dir() / _PID_FILENAME
