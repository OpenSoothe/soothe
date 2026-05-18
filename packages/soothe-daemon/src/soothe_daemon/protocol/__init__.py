"""Protocol infrastructure for daemon communication (RFC-0013).

This submodule provides:
- MessageRouter: Transport-agnostic message dispatch
- ProtocolError: Base exception for protocol errors
- validate_message: Message structure validation
- validate_message_size: Message size validation
- create_error_response: Error response creation
- Error code constants: ERROR_INVALID_MESSAGE, ERROR_INVALID_JSON, etc.
"""

from soothe_daemon.protocol.router import MessageRouter
from soothe_daemon.protocol.validation import (
    ERROR_INTERNAL_ERROR,
    ERROR_INVALID_JSON,
    ERROR_INVALID_MESSAGE,
    ERROR_RATE_LIMITED,
    ERROR_UNKNOWN_MESSAGE_TYPE,
    ProtocolError,
    create_error_response,
    validate_message,
    validate_message_size,
)

__all__ = [
    "MessageRouter",
    "ProtocolError",
    "validate_message",
    "validate_message_size",
    "create_error_response",
    "ERROR_INVALID_MESSAGE",
    "ERROR_INVALID_JSON",
    "ERROR_RATE_LIMITED",
    "ERROR_INTERNAL_ERROR",
    "ERROR_UNKNOWN_MESSAGE_TYPE",
]
