"""Transport-agnostic message validation (RFC-0013).

This module provides message validation for the unified daemon protocol.
It validates message structure without transport-specific concerns.
"""

from __future__ import annotations

from typing import Any


class ProtocolError(Exception):
    """Base exception for protocol errors."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize protocol error.

        Args:
            code: Error code (e.g., "INVALID_MESSAGE").
            message: Human-readable error message.
            details: Optional additional error details.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to message dict.

        Returns:
            Error message dict suitable for sending to clients.
        """
        result: dict[str, Any] = {
            "type": "error",
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


def validate_message(msg: dict[str, Any]) -> list[str]:
    """Validate message structure according to RFC-0013 protocol.

    This function performs structural validation only. It checks that
    required fields are present and have the correct types.

    Args:
        msg: Message dict to validate.

    Returns:
        List of validation error messages. Empty list if valid.
    """
    errors = []

    # All messages must have a "type" field
    if "type" not in msg:
        errors.append("Missing required field: type")
        return errors

    msg_type = msg["type"]

    # Validate based on message type
    if msg_type == "command":
        if "cmd" not in msg:
            errors.append("Command message missing required field: cmd")
        elif not isinstance(msg.get("cmd"), str):
            errors.append("Command cmd must be a string")

    elif msg_type == "daemon_ready":
        # No additional fields required
        pass

    elif msg_type == "detach":
        # No additional fields required
        pass

    elif msg_type == "skills_list":
        # Optional request_id is validated elsewhere; no extra fields required.
        pass

    elif msg_type == "models_list":
        # Optional request_id only; catalog is derived from daemon SootheConfig.
        pass

    elif msg_type == "invoke_skill":
        if "skill" not in msg:
            errors.append("invoke_skill message missing required field: skill")
        elif not isinstance(msg.get("skill"), str):
            errors.append("invoke_skill skill must be a string")
        if "args" in msg and not isinstance(msg["args"], str):
            errors.append("invoke_skill args must be a string")

    else:
        # Unknown message type - allow but log warning
        # This provides forward compatibility for new message types
        pass

    return errors


def validate_message_size(msg: dict[str, Any], max_size_bytes: int = 10 * 1024 * 1024) -> bool:
    """Validate that message size is within limits.

    Args:
        msg: Message dict to validate.
        max_size_bytes: Maximum size in bytes (default: 10MB).

    Returns:
        True if message is within size limit, False otherwise.
    """
    import json

    try:
        # Estimate size by encoding to JSON
        encoded = json.dumps(msg, ensure_ascii=False)
        return len(encoded.encode("utf-8")) <= max_size_bytes
    except (TypeError, ValueError):
        return False


# Error code constants per RFC-0013
ERROR_INVALID_MESSAGE = "INVALID_MESSAGE"
ERROR_INVALID_JSON = "INVALID_JSON"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERROR_UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"


def create_error_response(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Create an error message response.

    Args:
        code: Error code.
        message: Error message.
        details: Optional error details.

    Returns:
        Error message dict.
    """
    error = ProtocolError(code, message, details)
    return error.to_dict()
