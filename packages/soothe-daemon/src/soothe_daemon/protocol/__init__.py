"""Protocol infrastructure for daemon communication.

This submodule provides:
- MessageRouter: Transport-agnostic message dispatch
- ErrorCode: Numeric error code registry (RFC-450 §7.3)
- ProtocolError: Structured exception with numeric code (RFC-450 §7.4)
- build_error_response: Wire-ready error envelope constructor
- validate_message: Pydantic schema validation at transport boundary (RFC-450 §6)
- validate_message_size: Message size validation
- PARAMS_REGISTRY: Maps (type, method) to Pydantic params model (RFC-450 §6.2)

The numeric error model (ErrorCode / ProtocolError / build_error_response)
is the protocol-1 canonical API.
"""

from soothe_daemon.protocol.error_codes import (
    ErrorCode,
    ProtocolError,
    build_error_response,
    daemon_not_ready,
    goal_not_found,
    internal_error,
    invalid_params,
    job_not_found,
    loop_not_found,
    method_not_found,
    skill_not_found,
)
from soothe_daemon.protocol.router import MessageRouter
from soothe_daemon.protocol.schemas import PARAMS_REGISTRY
from soothe_daemon.protocol.validation import (
    VALID_TYPES,
    validate_message,
    validate_message_size,
)

__all__ = [
    "MessageRouter",
    "ErrorCode",
    "ProtocolError",
    "build_error_response",
    # Convenience constructors (RFC-450 §7.4)
    "loop_not_found",
    "job_not_found",
    "goal_not_found",
    "skill_not_found",
    "invalid_params",
    "method_not_found",
    "daemon_not_ready",
    "internal_error",
    # Validation helpers
    "validate_message",
    "validate_message_size",
    "VALID_TYPES",
    "PARAMS_REGISTRY",
]
