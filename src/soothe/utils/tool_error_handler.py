"""Tool error handling decorator."""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


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
                logger.exception("%s failed: %s", tool_name, error_msg)
                if return_type == "dict":
                    return {"error": error_msg}
                return f"Error: {error_msg}"

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


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

    # HTTP errors
    if hasattr(exc, "response"):  # HTTPStatusError
        status = getattr(exc.response, "status_code", "unknown")
        return f"HTTP error {status}"

    # Default: show type and message
    return f"{error_type}: {error_msg}"
