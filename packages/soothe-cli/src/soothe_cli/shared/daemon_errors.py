"""Shared daemon execution error presentation for CLI and TUI."""

from __future__ import annotations

# Partial match for pool_runner RuntimeError when an OS worker exits mid-turn.
DAEMON_WORKER_SUBPROCESS_LOST = "Worker subprocess exited unexpectedly during query execution"

_FRIENDLY_WORKER_SUBPROCESS_LOST = (
    "The daemon execution worker stopped unexpectedly (for example after the pool "
    "recycled an idle subprocess). Send your message again."
)


def friendly_daemon_execution_error(exc: BaseException | str) -> str:
    """Map known daemon failures to concise, actionable copy."""
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
