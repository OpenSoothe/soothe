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
    if msg_type == "input":
        if "text" not in msg:
            errors.append("Input message missing required field: text")
        elif not isinstance(msg.get("text"), str):
            errors.append("Input text must be a string")

        # Optional fields
        if "autonomous" in msg and not isinstance(msg["autonomous"], bool):
            errors.append("Input autonomous must be a boolean")
        if "max_iterations" in msg and not isinstance(msg["max_iterations"], int):
            errors.append("Input max_iterations must be an integer")

    elif msg_type == "command":
        if "cmd" not in msg:
            errors.append("Command message missing required field: cmd")
        elif not isinstance(msg.get("cmd"), str):
            errors.append("Command cmd must be a string")

    elif msg_type == "resume_thread":
        if "thread_id" not in msg:
            errors.append("Resume thread message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("Resume thread thread_id must be a string")

    elif msg_type == "daemon_ready":
        # No additional fields required
        pass

    # Thread management messages (RFC-0017)
    elif msg_type == "thread_list":
        # filter is optional
        if "filter" in msg and not isinstance(msg["filter"], dict):
            errors.append("thread_list filter must be an object")
        # include_stats is optional boolean
        if "include_stats" in msg and not isinstance(msg["include_stats"], bool):
            errors.append("thread_list include_stats must be a boolean")

    elif msg_type == "thread_create":
        # initial_message is optional string
        if "initial_message" in msg and not isinstance(msg["initial_message"], str):
            errors.append("thread_create initial_message must be a string")
        # metadata is optional object
        if "metadata" in msg and not isinstance(msg["metadata"], dict):
            errors.append("thread_create metadata must be an object")

    elif msg_type == "thread_get":
        if "thread_id" not in msg:
            errors.append("thread_get message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("thread_get thread_id must be a string")

    elif msg_type == "thread_archive":
        if "thread_id" not in msg:
            errors.append("thread_archive message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("thread_archive thread_id must be a string")

    elif msg_type == "thread_delete":
        if "thread_id" not in msg:
            errors.append("thread_delete message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("thread_delete thread_id must be a string")

    elif msg_type == "thread_messages":
        if "thread_id" not in msg:
            errors.append("thread_messages message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("thread_messages thread_id must be a string")
        # limit and offset are optional integers
        if "limit" in msg and not isinstance(msg["limit"], int):
            errors.append("thread_messages limit must be an integer")
        if "offset" in msg and not isinstance(msg["offset"], int):
            errors.append("thread_messages offset must be an integer")

    elif msg_type == "thread_artifacts":
        if "thread_id" not in msg:
            errors.append("thread_artifacts message missing required field: thread_id")
        elif not isinstance(msg.get("thread_id"), str):
            errors.append("thread_artifacts thread_id must be a string")

    elif msg_type == "detach":
        # No additional fields required
        pass

    elif msg_type == "auth":
        if "token" not in msg:
            errors.append("Auth message missing required field: token")
        elif not isinstance(msg.get("token"), str):
            errors.append("Auth token must be a string")

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


def create_error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
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


# Error code constants per RFC-0013
ERROR_INVALID_MESSAGE = "INVALID_MESSAGE"
ERROR_INVALID_JSON = "INVALID_JSON"
ERROR_AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
ERROR_AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERROR_UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"
