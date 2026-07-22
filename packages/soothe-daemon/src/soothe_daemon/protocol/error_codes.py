"""Numeric error code registry and structured protocol error helpers.

Implements the protocol-1 error model (RFC-450 §7). The registry is a
JSON-RPC 2.0-style numeric scheme with reserved ranges; all wire error
responses are produced through the `RpcProtocolError` helper, making a
malformed error structurally impossible. Error envelopes use the JSON-RPC
nested ``error:{code, message, data?}`` object per RFC-450 §7.1.

Public API:
    ErrorCode            -- IntEnum of all numeric error codes
    RpcProtocolError        -- exception carrying code, message, optional data
    build_error_response -- wire envelope dict for an error
    convenience constructors: loop_not_found, job_not_found, goal_not_found,
        skill_not_found, invalid_params, method_not_found, daemon_not_ready,
        internal_error

Ranges (RFC-450 §7.3):
    -32768..-32000  Protocol-level (JSON-RPC convention)
    -32000..-32099  Server state
    -32100..-32199  Authorization/session
    -32200..-32299  Resource not found
    -32300..-32399  State conflicts
    -32400..-32499  Operation failures
    -32500..-32599  Job operation failures
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

__all__ = [
    "ErrorCode",
    "RpcProtocolError",
    "build_error_response",
    "loop_not_found",
    "job_not_found",
    "goal_not_found",
    "skill_not_found",
    "invalid_params",
    "method_not_found",
    "daemon_not_ready",
    "internal_error",
]


class ErrorCode(IntEnum):
    """Numeric error codes with reserved ranges (RFC-450 §7.3).

    The enum intentionally aliases legacy string code names to their new
    numeric equivalents so call sites can migrate incrementally.
    """

    # Protocol-level (-32768 to -32000)
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Server state (-32000 to -32099)
    RATE_LIMITED = -32000
    DAEMON_STARTING = -32001
    DAEMON_BUSY = -32002
    DAEMON_DEGRADED = -32003
    DAEMON_ERROR = -32004

    # Authorization/session (-32100 to -32199)
    NO_LOOP_SUBSCRIPTION = -32100
    LOOP_NOT_SUBSCRIBED = -32101
    NO_SESSION = -32102
    AUTH_FAILED = -32103
    AUTH_EXPIRED = -32104

    # Resource not found (-32200 to -32299)
    LOOP_NOT_FOUND = -32200
    JOB_NOT_FOUND = -32201
    GOAL_NOT_FOUND = -32202
    SKILL_NOT_FOUND = -32203

    # State conflicts (-32300 to -32399)
    JOB_ALREADY_PAUSED = -32300
    JOB_NOT_PAUSED = -32301
    JOB_COMPLETED = -32302
    LOOP_ALREADY_ACTIVE = -32303

    # Operation failures (-32400 to -32499)
    SKILL_LOAD_FAILED = -32400
    RUNNER_UNAVAILABLE = -32401
    AUTOPILOT_NOT_READY = -32402
    CARD_MANAGER_UNAVAILABLE = -32403
    CARDS_FETCH_FAILED = -32404
    LOOP_CONTEXT_ERROR = -32405
    LOOP_STATE_ERROR = -32406
    WORKSPACE_RESOLUTION_FAILED = -32407

    # Job operation failures (-32500 to -32599)
    JOB_CREATE_FAILED = -32500
    JOB_PAUSE_FAILED = -32501
    JOB_RESUME_FAILED = -32502
    JOB_CANCEL_FAILED = -32503
    LOOP_REATTACH_FAILED = -32504


# Severity metadata per RFC-450 §7.2. Maps each ErrorCode to one of
# "fatal", "error", "warn". Kept as a plain dict (not on the enum) so the
# IntEnum stays a pure numeric value and JSON-serializes cleanly.
_SEVERITY: dict[ErrorCode, str] = {
    ErrorCode.PARSE_ERROR: "fatal",
    ErrorCode.INVALID_REQUEST: "error",
    ErrorCode.METHOD_NOT_FOUND: "error",
    ErrorCode.INVALID_PARAMS: "error",
    ErrorCode.INTERNAL_ERROR: "fatal",
    ErrorCode.RATE_LIMITED: "warn",
    ErrorCode.DAEMON_STARTING: "warn",
    ErrorCode.DAEMON_BUSY: "warn",
    ErrorCode.DAEMON_DEGRADED: "warn",
    ErrorCode.DAEMON_ERROR: "fatal",
    ErrorCode.NO_LOOP_SUBSCRIPTION: "error",
    ErrorCode.LOOP_NOT_SUBSCRIBED: "error",
    ErrorCode.NO_SESSION: "error",
    ErrorCode.AUTH_FAILED: "error",
    ErrorCode.AUTH_EXPIRED: "error",
    ErrorCode.LOOP_NOT_FOUND: "error",
    ErrorCode.JOB_NOT_FOUND: "error",
    ErrorCode.GOAL_NOT_FOUND: "error",
    ErrorCode.SKILL_NOT_FOUND: "error",
    ErrorCode.JOB_ALREADY_PAUSED: "warn",
    ErrorCode.JOB_NOT_PAUSED: "warn",
    ErrorCode.JOB_COMPLETED: "warn",
    ErrorCode.LOOP_ALREADY_ACTIVE: "warn",
    ErrorCode.SKILL_LOAD_FAILED: "error",
    ErrorCode.RUNNER_UNAVAILABLE: "fatal",
    ErrorCode.AUTOPILOT_NOT_READY: "warn",
    ErrorCode.CARD_MANAGER_UNAVAILABLE: "error",
    ErrorCode.CARDS_FETCH_FAILED: "error",
    ErrorCode.LOOP_CONTEXT_ERROR: "error",
    ErrorCode.LOOP_STATE_ERROR: "error",
    ErrorCode.WORKSPACE_RESOLUTION_FAILED: "error",
    ErrorCode.JOB_CREATE_FAILED: "error",
    ErrorCode.JOB_PAUSE_FAILED: "error",
    ErrorCode.JOB_RESUME_FAILED: "error",
    ErrorCode.JOB_CANCEL_FAILED: "error",
    ErrorCode.LOOP_REATTACH_FAILED: "error",
}


def severity_of(code: ErrorCode) -> str:
    """Return the severity tag for an error code (RFC-450 §7.2).

    Args:
        code: An `ErrorCode` member.

    Returns:
        One of ``"fatal"``, ``"error"``, ``"warn"``.
    """
    return _SEVERITY.get(code, "error")


class RpcProtocolError(Exception):
    """Structured protocol error carrying a numeric code (RFC-450 §7.4).

    Handlers raise `RpcProtocolError` (or a convenience constructor); the
    transport layer catches it and serializes via `to_dict` /
    `build_error_response`.

    Attributes:
        code: `ErrorCode` member (also an int).
        message: Human-readable summary string.
        data: Machine-parseable details dict (empty dict when unset).
        severity: One of ``"fatal"``, ``"error"``, ``"warn"``.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        severity: str | None = None,
    ) -> None:
        """Initialize a protocol error.

        Args:
            code: Numeric error code from the `ErrorCode` registry.
            message: Human-readable error summary.
            data: Optional machine-parseable details. Defaults to empty dict.
            severity: Optional severity override (``"fatal"``/``"error"``
                /``"warn"``). Defaults to the registry severity for ``code``.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data if data else {}
        self.severity = severity if severity is not None else severity_of(code)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error object to a wire-ready envelope.

        Produces the ``{type:'error', error:{code, message, data?}}`` envelope
        per RFC-450 §7.1. The nested ``error`` object always carries ``code``
        and ``message``; ``data`` is omitted when empty (no extra context).

        Returns:
            Dict with keys ``type`` and ``error`` (a dict with ``code`` (int),
            ``message``, and optionally ``data``).
        """
        error_obj: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.data:
            error_obj["data"] = self.data
        return {"type": "error", "error": error_obj}

    def to_envelope(self, *, proto: str = "1", request_id: str | None = None) -> dict[str, Any]:
        """Build a full wire-ready error message envelope (RFC-450 §7.1).

        Args:
            proto: Protocol version string (default ``"1"``).
            request_id: The originating request's correlation id. When
                ``None`` (e.g. the original message was a notification),
                the ``id`` field is omitted.

        Returns:
            Envelope dict shaped as
            ``{proto, type:'error', error:{code, message, data?}, id?}``.
        """
        return build_error_response(
            self.code,
            self.message,
            request_id=request_id,
            data=self.data if self.data else None,
            proto=proto,
        )


def build_error_response(
    code: ErrorCode,
    message: str,
    request_id: str | None = None,
    data: dict[str, Any] | None = None,
    *,
    proto: str = "1",
) -> dict[str, Any]:
    """Construct a wire-ready error response envelope (RFC-450 §7.1).

    The envelope always includes ``proto``, ``type``, and a nested ``error``
    object with ``code`` and ``message``. ``data`` is included in the
    ``error`` object only when non-empty; ``id`` is included only when
    ``request_id`` is provided (i.e. the original request expected a response).

    Args:
        code: Numeric error code from the `ErrorCode` registry.
        message: Human-readable error summary.
        request_id: Originating request correlation id, or ``None`` for
            notifications / parse failures where no id is known.
        data: Optional machine-parseable details dict.
        proto: Protocol version string (default ``"1"``).

    Returns:
        Dict in the form
        ``{proto, type:'error', error:{code, message, data?}, id?}``.
    """
    error_obj: dict[str, Any] = {
        "code": code.value,
        "message": message,
    }
    if data:
        error_obj["data"] = data
    envelope: dict[str, Any] = {
        "proto": proto,
        "type": "error",
        "error": error_obj,
    }
    if request_id is not None:
        envelope["id"] = request_id
    return envelope


# ---------------------------------------------------------------------------
# Convenience constructors (RFC-450 §7.4)
# ---------------------------------------------------------------------------


def loop_not_found(loop_id: str) -> RpcProtocolError:
    """Build a `LOOP_NOT_FOUND` error for a missing loop.

    Args:
        loop_id: The loop id that could not be located.

    Returns:
        A `RpcProtocolError` with code `-32200` and ``{loop_id}`` data.
    """
    return RpcProtocolError(
        ErrorCode.LOOP_NOT_FOUND,
        f"Loop {loop_id} not found",
        data={"loop_id": loop_id},
    )


def job_not_found(job_id: str) -> RpcProtocolError:
    """Build a `JOB_NOT_FOUND` error for a missing job.

    Args:
        job_id: The job id that could not be located.

    Returns:
        A `RpcProtocolError` with code `-32201` and ``{job_id}`` data.
    """
    return RpcProtocolError(
        ErrorCode.JOB_NOT_FOUND,
        f"Job {job_id} not found",
        data={"job_id": job_id},
    )


def goal_not_found(goal_id: str) -> RpcProtocolError:
    """Build a `GOAL_NOT_FOUND` error for a missing goal.

    Args:
        goal_id: The goal id that could not be located.

    Returns:
        A `RpcProtocolError` with code `-32202` and ``{goal_id}`` data.
    """
    return RpcProtocolError(
        ErrorCode.GOAL_NOT_FOUND,
        f"Goal {goal_id} not found",
        data={"goal_id": goal_id},
    )


def skill_not_found(skill: str) -> RpcProtocolError:
    """Build a `SKILL_NOT_FOUND` error for a missing skill.

    Args:
        skill: The skill name that could not be located.

    Returns:
        A `RpcProtocolError` with code `-32203` and ``{skill}`` data.
    """
    return RpcProtocolError(
        ErrorCode.SKILL_NOT_FOUND,
        f"Skill {skill!r} not found",
        data={"skill": skill},
    )


def invalid_params(field: str, reason: str) -> RpcProtocolError:
    """Build an `INVALID_PARAMS` error for a bad parameter.

    Args:
        field: The parameter field name that failed validation.
        reason: Human-readable explanation of why it is invalid.

    Returns:
        A `RpcProtocolError` with code `-32602` and ``{field, reason}`` data.
    """
    return RpcProtocolError(
        ErrorCode.INVALID_PARAMS,
        f"Invalid parameter: {field}",
        data={"field": field, "reason": reason},
    )


def method_not_found(method: str) -> RpcProtocolError:
    """Build a `METHOD_NOT_FOUND` error for an unknown method/type.

    Args:
        method: The method (or type) string the client requested.

    Returns:
        A `RpcProtocolError` with code `-32601` and ``{method}`` data.
    """
    return RpcProtocolError(
        ErrorCode.METHOD_NOT_FOUND,
        f"Method not found: {method}",
        data={"method": method},
    )


def daemon_not_ready(state: str) -> RpcProtocolError:
    """Build a `DAEMON_STARTING` error for a not-yet-ready daemon.

    Args:
        state: Current daemon readiness state (e.g. ``"starting"``,
            ``"warming"``).

    Returns:
        A `RpcProtocolError` with code `-32001` and ``{state}`` data.
    """
    return RpcProtocolError(
        ErrorCode.DAEMON_STARTING,
        f"Daemon not ready (state: {state})",
        data={"state": state},
    )


def internal_error(detail: str) -> RpcProtocolError:
    """Build an `INTERNAL_ERROR` for an unexpected server failure.

    Args:
        detail: Short diagnostic string (avoid leaking stack traces to
            clients).

    Returns:
        A `RpcProtocolError` with code `-32603` and ``{detail}`` data.
    """
    return RpcProtocolError(
        ErrorCode.INTERNAL_ERROR,
        "Internal server error",
        data={"detail": detail},
    )
