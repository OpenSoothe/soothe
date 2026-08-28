"""Protocol infrastructure for daemon communication."""

from soothe_daemon.protocol.error_codes import (
    ErrorCode,
    RpcProtocolError,
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
    "RpcProtocolError",
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
