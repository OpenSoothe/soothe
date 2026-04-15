"""Error formatting utilities for CLI output."""

from __future__ import annotations

import logging

from soothe_daemon.utils.text_preview import log_preview

logger = logging.getLogger(__name__)

_MAX_ERROR_MSG_LENGTH = 100


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

    Examples:
        >>> format_cli_error(TimeoutError("Browser did not start within 30 seconds"))
        "TimeoutError: Browser did not start within 30 seconds"

        >>> format_cli_error(TimeoutError("Browser did not start"), context="browser launch")
        "Browser launch failed: TimeoutError: Browser did not start"

        >>> format_cli_error("Connection refused")
        "Connection refused"
    """
    # Extract error message
    if isinstance(error, Exception):
        error_type = type(error).__name__
        error_msg = str(error)

        # Simplify common error patterns
        simplified_msg = _simplify_error_message(error_type, error_msg)

        if context:
            if show_type:
                return f"{context} failed: {error_type}: {simplified_msg}"
            return f"{context} failed: {simplified_msg}"
        if show_type:
            return f"{error_type}: {simplified_msg}"
        return simplified_msg
    # String error message
    error_str = str(error)
    if context:
        return f"{context} failed: {error_str}"
    return error_str


def _simplify_error_message(error_type: str, error_msg: str) -> str:
    """Simplify verbose error messages for CLI display.

    Args:
        error_type: Exception type name.
        error_msg: Original error message.

    Returns:
        Simplified error message.
    """
    # TimeoutError simplifications
    if error_type == "TimeoutError":
        # Simplify browser_use timeout messages
        if "Browser did not start within" in error_msg:
            return "Browser startup timeout"
        if "Event handler" in error_msg and "timed out" in error_msg:
            # Extract just the core issue, not the full event chain
            return "Operation timed out"

    # ConnectionError simplifications
    if error_type in ("ConnectionError", "ConnectionRefusedError"):
        if "Connection refused" in error_msg:
            return "Connection refused (service may not be running)"
        return "Connection failed"

    # ImportError simplifications
    if error_type == "ImportError":
        # Extract module name if possible
        if "No module named" in error_msg:
            return error_msg  # Already concise
        return f"Missing dependency: {error_msg}"

    # OSError simplifications
    if error_type == "OSError":
        if "No such file or directory" in error_msg:
            return "File or directory not found"
        if "Permission denied" in error_msg:
            return "Permission denied"
        return "System error"

    # For other errors, return original message if it's concise
    if len(error_msg) <= _MAX_ERROR_MSG_LENGTH:
        return error_msg

    # Truncate long messages
    return log_preview(error_msg, _MAX_ERROR_MSG_LENGTH)


def log_exception_simplified(
    logger: logging.Logger,
    error: Exception,
    *,
    message: str = "Operation failed",
    context: str | None = None,
) -> None:
    """Log full exception traceback to logs, return simplified CLI message.

    This is a convenience function that logs the full exception with traceback
    using logger.exception() while returning a simplified message for CLI display.

    Args:
        logger: Logger instance to use.
        error: Exception that occurred.
        message: Log message prefix.
        context: Optional context for CLI message.

    Returns:
        Simplified error message for CLI display.

    Example:
        >>> try:
        ...     await risky_operation()
        ... except Exception as e:
        ...     cli_msg = log_exception_simplified(logger, e, context="browser launch")
        ...     print(f"Error: {cli_msg}")
    """
    # Log full traceback to file
    logger.exception(message)

    # Return simplified message for CLI
    return format_cli_error(error, context=context)


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

    Example:
        >>> emit_error_event(TimeoutError("Browser timeout"), context="browser launch")
        {'type': 'soothe.error.general', 'error': 'Browser launch failed: TimeoutError: Browser startup timeout'}
    """
    from soothe_daemon.core.event_catalog import ERROR

    simplified = format_cli_error(error, context=context)
    return {"type": ERROR, "error": simplified}
