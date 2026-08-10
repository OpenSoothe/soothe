"""Shared daemon execution error presentation for CLI and TUI."""

from __future__ import annotations

# Partial match for pool_runner RuntimeError when an OS worker exits mid-turn.
DAEMON_WORKER_SUBPROCESS_LOST = "Worker subprocess exited unexpectedly during query execution"

# Partial match for thread_runner RuntimeError when a worker thread dies mid-turn.
DAEMON_WORKER_THREAD_LOST = "Worker thread exited unexpectedly during query execution"

_FRIENDLY_WORKER_SUBPROCESS_LOST = (
    "The daemon execution worker stopped unexpectedly (for example after the pool "
    "recycled an idle subprocess). Send your message again."
)

_FRIENDLY_WORKER_THREAD_LOST = (
    "The daemon execution worker stopped unexpectedly during your request. "
    "Send your message again, or use /resume to recover the loop."
)

_FRIENDLY_DAEMON_CONNECTION_LOST = (
    "Daemon connection lost (the daemon may have restarted). "
    "Send your message again to reconnect and continue this loop."
)

# Partial match for the attach-only idle timeout raised by ``iter_turn_chunks``
# when a stale ``live`` probe attaches to a loop whose runner already exited.
ATTACH_IDLE_TIMEOUT_MARKER = "attach window"

_FRIENDLY_ATTACH_IDLE_TIMEOUT = (
    "No follow-on turn started within the attach window; the prior turn had "
    "already completed. Ready for your next message."
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
    if is_attach_idle_timeout(exc):
        return _FRIENDLY_ATTACH_IDLE_TIMEOUT
    if isinstance(exc, RuntimeError) and DAEMON_WORKER_SUBPROCESS_LOST in str(exc):
        return _FRIENDLY_WORKER_SUBPROCESS_LOST
    if isinstance(exc, RuntimeError) and DAEMON_WORKER_THREAD_LOST in str(exc):
        return _FRIENDLY_WORKER_THREAD_LOST
    text = str(exc)
    if DAEMON_WORKER_SUBPROCESS_LOST in text:
        return _FRIENDLY_WORKER_SUBPROCESS_LOST
    if DAEMON_WORKER_THREAD_LOST in text:
        return _FRIENDLY_WORKER_THREAD_LOST
    return text if isinstance(exc, str) else str(exc)


def is_daemon_worker_subprocess_lost(exc: BaseException | str) -> bool:
    """Return whether an error indicates a pool worker process exited mid-query."""
    text = str(exc)
    return DAEMON_WORKER_SUBPROCESS_LOST in text


def is_daemon_worker_thread_lost(exc: BaseException | str) -> bool:
    """Return whether an error indicates a pool worker thread exited mid-query."""
    text = str(exc)
    return DAEMON_WORKER_THREAD_LOST in text


def is_attach_idle_timeout(exc: BaseException | str) -> bool:
    """Return whether an error is the attach-only idle timeout.

    Raised by ``iter_turn_chunks`` when a stale ``live`` probe attached to a
    loop whose runner had already exited (no follow-on turn materialized).
    """
    return ATTACH_IDLE_TIMEOUT_MARKER in str(exc)
