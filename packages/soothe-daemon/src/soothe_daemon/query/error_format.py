"""Error formatting utilities for daemon query-engine output."""

from __future__ import annotations

import logging

from soothe_nano.utils.text_preview import log_preview

logger = logging.getLogger(__name__)

_MAX_ERROR_MSG_LENGTH = 200


def format_cli_error(
    error: Exception | str,
    *,
    context: str | None = None,
    show_type: bool = True,
) -> str:
    """Format an error message for CLI display (simplified, user-friendly).

    Converts verbose exceptions into concise, actionable messages suitable for
    terminal output. Full details remain in log files.

    Args:
    error: Exception instance or error message string.
    context: Optional context about what operation failed.
    show_type: Whether to include exception type name.

    Returns:
    Simplified error message for CLI display.
    """
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


def _first_meaningful_line(text: str) -> str:
    """Extract the most useful line from a possibly multi-line error string.

    For single-line errors, returns the line as-is. For multi-line errors
    (stack traces, embedded JSON), returns the **last** non-empty line —
    that's where the exception cause sits at the bottom of a Python traceback.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text
    if len(lines) == 1:
        return lines[0]
    return lines[-1]


def _simplify_error_message(error_type: str, error_msg: str) -> str:
    """Simplify verbose error messages for CLI display.

    Multi-line / stack-trace-laden errors are reduced to their first
    meaningful line, capped at `_MAX_ERROR_MSG_LENGTH` chars. Known
    error types with actionable suggestions are mapped explicitly.
    """
    if not error_msg:
        return error_msg

    # Known error types with actionable suggestions.
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

    # General case: reduce multi-line / stack-trace-laden errors to a single
    # actionable line, then cap the length.
    first = _first_meaningful_line(error_msg)
    if len(first) <= _MAX_ERROR_MSG_LENGTH:
        return first
    return log_preview(first, _MAX_ERROR_MSG_LENGTH)


def emit_error_event(
    error: Exception | str,
    *,
    context: str | None = None,
) -> dict[str, str]:
    """Create a soothe.error.general event dict with simplified message.

    Args:
    error: Exception or error message.
    context: Optional context about what failed.

    Returns:
    Event dict with type='soothe.error.general' and simplified message.
    """
    from soothe.events import ERROR

    simplified = format_cli_error(error, context=context)
    return {"type": ERROR, "error": simplified}
