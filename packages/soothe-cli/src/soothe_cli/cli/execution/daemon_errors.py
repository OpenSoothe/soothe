"""Shared daemon execution error presentation for CLI and TUI."""

from __future__ import annotations

# Partial match for pool_runner RuntimeError when an OS worker exits mid-turn.
DAEMON_WORKER_SUBPROCESS_LOST = "Worker subprocess exited unexpectedly during query execution"

_FRIENDLY_WORKER_SUBPROCESS_LOST = (
    "The daemon execution worker stopped unexpectedly (for example after the pool "
    "recycled an idle subprocess). Send your message again."
)

_FRIENDLY_DAEMON_CONNECTION_LOST = (
    "Daemon connection lost (the daemon may have restarted). "
    "Send your message again to reconnect and continue this loop."
)


def is_daemon_connection_error(exc: BaseException | str) -> bool:
    """Return whether an error indicates the daemon WebSocket is unavailable."""
    if isinstance(exc, ConnectionError):
        return True
    text = str(exc).lower()
    markers = (
        "connection closed",
        "connection lost",
        "not connected to daemon",
        "failed to connect to daemon",
        "connection refused",
        "connection error",
    )
    return any(m in text for m in markers)


def friendly_daemon_connection_error(exc: BaseException | str) -> str:
    """Map transport failures to concise, actionable copy for CLI and TUI."""
    if is_daemon_connection_error(exc):
        return _FRIENDLY_DAEMON_CONNECTION_LOST
    return friendly_daemon_execution_error(exc)


def friendly_daemon_execution_error(exc: BaseException | str) -> str:
    """Map known daemon failures to concise, actionable copy."""
    if is_daemon_connection_error(exc):
        return _FRIENDLY_DAEMON_CONNECTION_LOST
    if isinstance(exc, RuntimeError) and DAEMON_WORKER_SUBPROCESS_LOST in str(exc):
        return _FRIENDLY_WORKER_SUBPROCESS_LOST
    text = str(exc)
    if DAEMON_WORKER_SUBPROCESS_LOST in text:
        return _FRIENDLY_WORKER_SUBPROCESS_LOST
    return text if isinstance(exc, str) else str(exc)


def is_daemon_worker_subprocess_lost(exc: BaseException | str) -> bool:
    """Return whether an error indicates a pool worker process exited mid-query."""
    text = str(exc)
    return DAEMON_WORKER_SUBPROCESS_LOST in text
