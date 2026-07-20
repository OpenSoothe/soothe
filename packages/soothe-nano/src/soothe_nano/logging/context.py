"""Thread ID context variable for structured logging."""

from __future__ import annotations

import contextvars

_current_thread_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_thread_id", default=None
)


def set_thread_id(thread_id: str | None) -> None:
    """Set the current thread ID for structured log records.

    Args:
        thread_id: The conversation thread ID to include in log messages,
            or ``None`` to clear the current value.
    """
    _current_thread_id.set(thread_id)


def get_thread_id() -> str | None:
    """Get the current thread ID for structured log records.

    Returns:
        The current thread ID, or ``None`` if not set.
    """
    return _current_thread_id.get()
