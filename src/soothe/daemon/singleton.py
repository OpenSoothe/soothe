"""PID file and singleton lock management for Soothe daemon."""

from __future__ import annotations

import contextlib
import fcntl
import os

from soothe.daemon.paths import pid_path, socket_path


def write_pid() -> None:
    """Write current process PID to the PID file."""
    pf = pid_path()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(os.getpid()))


def cleanup_pid() -> None:
    """Remove the PID file if it exists."""
    pf = pid_path()
    if pf.exists():
        with contextlib.suppress(OSError):
            pf.unlink()


def cleanup_socket() -> None:
    """Remove the socket file if it exists."""
    sock = socket_path()
    if sock.exists():
        with contextlib.suppress(OSError):
            sock.unlink()


def acquire_pid_lock() -> int | None:
    """Try to acquire an exclusive lock on the PID file.

    Returns:
        File descriptor on success, None if another daemon holds the lock.
    """
    pf = pid_path()
    pf.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(pf), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_bytes = str(os.getpid()).encode()
        os.write(fd, pid_bytes)
        os.ftruncate(fd, len(pid_bytes))
        os.fsync(fd)
    except OSError:
        return None
    else:
        return fd


def release_pid_lock(fd: int) -> None:
    """Release the PID file lock and clean up.

    Args:
        fd: File descriptor returned by acquire_pid_lock().
    """
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    cleanup_pid()
