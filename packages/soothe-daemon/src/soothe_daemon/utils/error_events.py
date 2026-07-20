"""Daemon-facing wire error event helpers."""

from __future__ import annotations

from soothe.foundation.events import ERROR
from soothe_nano.utils.text_preview import log_preview

_MAX_ERROR_MSG_LENGTH = 100


def _simplify_error_message(error_type: str, error_msg: str) -> str:
    if error_type == "EnhancedTimeoutError":
        if "large prompt" in error_msg:
            return "Timeout (large prompt) - try simplifying or splitting request"
        return "Timeout after retries - request may be too complex"

    if error_type == "TimeoutError":
        if "Browser did not start within" in error_msg:
            return "Browser startup timeout"
        if "Event handler" in error_msg and "timed out" in error_msg:
            return "Operation timed out"
        return "Operation timed out - retrying automatically"

    if error_type == "RuntimeError" and (
        "Worker subprocess exited unexpectedly during query execution" in error_msg
    ):
        return (
            "The daemon execution worker stopped unexpectedly (for example after the pool "
            "recycled an idle subprocess). Send your message again."
        )

    if error_type in ("ConnectionError", "ConnectionRefusedError"):
        if "Connection refused" in error_msg:
            return "Connection refused (service may not be running)"
        return "Connection failed"

    if error_type == "ImportError":
        if "No module named" in error_msg:
            return error_msg
        return f"Missing dependency: {error_msg}"

    if error_type == "OSError":
        if "No such file or directory" in error_msg:
            return "File or directory not found"
        if "Permission denied" in error_msg:
            return "Permission denied"
        return "System error"

    if len(error_msg) <= _MAX_ERROR_MSG_LENGTH:
        return error_msg

    return log_preview(error_msg, _MAX_ERROR_MSG_LENGTH)


def format_cli_error(
    error: Exception | str,
    *,
    context: str | None = None,
    show_type: bool = True,
) -> str:
    """Format an error message for user-facing daemon events."""
    if isinstance(error, Exception):
        error_type = type(error).__name__
        error_msg = str(error)
        simplified_msg = _simplify_error_message(error_type, error_msg)
        if context:
            if show_type:
                return f"{context} failed: {error_type}: {simplified_msg}"
            return f"{context} failed: {simplified_msg}"
        if show_type:
            return f"{error_type}: {simplified_msg}"
        return simplified_msg

    error_str = str(error)
    if context:
        return f"{context} failed: {error_str}"
    return error_str


def emit_error_event(
    error: Exception | str,
    *,
    context: str | None = None,
) -> dict[str, str]:
    """Create a ``soothe.error.general`` custom event payload."""
    simplified = format_cli_error(error, context=context)
    return {"type": ERROR, "error": simplified}
