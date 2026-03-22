"""Tool error handling decorator."""

import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# HTTP status codes for warning-level errors
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429


def tool_error_handler(tool_name: str, return_type: str = "dict") -> Callable[[Callable], Callable]:
    """Decorator for standardized tool error handling.

    Args:
        tool_name: Name of the tool for logging
        return_type: "dict" returns {"error": msg}, "str" returns "Error: msg"

    Catches all exceptions and returns error response instead of raising.
    Logs full traceback while returning simplified user message.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                error_msg = _simplify_error(exc)
                if _is_warning_level_error(exc):
                    logger.warning("%s failed: %s", tool_name, error_msg)
                else:
                    logger.exception("%s failed: %s", tool_name, error_msg)
                if return_type == "dict":
                    return {"error": error_msg}
                return f"Error: {error_msg}"

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                error_msg = _simplify_error(exc)
                if _is_warning_level_error(exc):
                    logger.warning("%s failed: %s", tool_name, error_msg)
                else:
                    logger.exception("%s failed: %s", tool_name, error_msg)
                if return_type == "dict":
                    return {"error": error_msg}
                return f"Error: {error_msg}"

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _is_warning_level_error(exc: Exception) -> bool:
    """Check if error should be logged as warning instead of error.

    Args:
        exc: Exception to check

    Returns:
        True if this should be logged as warning (non-critical/recoverable),
        False if it should be logged as error (unexpected/critical)
    """
    # Check for HTTP 403 Forbidden (API key issues, access denied)
    status = getattr(exc, "status", None)
    if status == HTTP_FORBIDDEN:
        return True

    # Check for HTTP 429 Too Many Requests (rate limiting)
    if status == HTTP_TOO_MANY_REQUESTS:
        return True

    # Check response object for status
    response = getattr(exc, "response", None)
    if response is not None:
        resp_status = getattr(response, "status_code", getattr(response, "status", None))
        if resp_status in (HTTP_FORBIDDEN, HTTP_TOO_MANY_REQUESTS):
            return True

    # Default: log as error
    return False


def _simplify_error(exc: Exception) -> str:
    """Convert exception to user-friendly message."""
    error_type = type(exc).__name__
    error_msg = str(exc)

    # DNS/Network errors
    if "nodename nor servname" in error_msg:
        return "DNS resolution failed - invalid domain name"
    if "ConnectError" in error_type or "ConnectionError" in error_type:
        if "Connection refused" in error_msg:
            return "Connection refused - service may not be running"
        return "Connection failed - network unreachable or service down"
    if "Timeout" in error_type or "timeout" in error_msg.lower():
        return "Request timed out"

    # HTTP errors - check response object
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "unknown")
        return f"HTTP error {status}"

    # Default: show type and message
    return f"{error_type}: {error_msg}"
