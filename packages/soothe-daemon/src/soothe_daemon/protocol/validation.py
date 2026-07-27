"""Transport-agnostic message validation (RFC-450 §6).

Provides Pydantic-based schema validation at the transport boundary.  Every
incoming message is validated against a params model from ``PARAMS_REGISTRY``
*before* router dispatch, so handlers receive pre-validated, typed params and
do not need inline ``if not loop_id:`` checks.

Public API:
    validate_message      -- validate a decoded message dict; returns list of
                             error strings (empty = valid)
    validate_message_size -- check encoded message size is within the limit
    VALID_TYPES           -- frozenset of all protocol-1 ``type`` values
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from soothe_sdk.wire.codec import MessageType

from soothe_daemon.protocol.schemas import PARAMS_REGISTRY

__all__ = [
    "validate_message",
    "validate_message_size",
    "VALID_TYPES",
]


# All valid ``type`` field values per RFC-450 §9.1. Derived from the canonical
# ``MessageType`` enum in ``soothe_sdk.wire.codec`` so adding a message class
# there updates daemon validation automatically.
VALID_TYPES: frozenset[str] = frozenset(m.value for m in MessageType)

# Envelope message classes that require ``proto == "1"`` (RFC-450 §8.1).
# ``ping`` and ``pong`` carry ``proto`` but are validated leniently, so they
# are exempt.
_CONTROL_TYPES: frozenset[str] = frozenset({MessageType.PING.value, MessageType.PONG.value})
_ENVELOPE_TYPES: frozenset[str] = VALID_TYPES - _CONTROL_TYPES


def validate_message(msg: dict[str, Any]) -> list[str]:
    """Validate a wire message against the schema registry (RFC-450 §6.3).

    Performs three checks:
    1. Envelope: ``type`` field is present and known.
    2. Schema lookup: a Pydantic model exists for ``(type, method)``.
    3. Params validation: ``model_validate`` succeeds.

    The daemon accepts protocol-1 envelopes (``{proto, type, method, params,
    id}``) plus the three non-envelope control types (``connection_init``,
    ``ping``, ``pong``). Legacy flat-form messages are rejected.

    Args:
        msg: Raw decoded message dict.

    Returns:
        List of validation error strings.  Empty list if the message is
        valid.  Each string is of the form ``"field: message"`` for params
        errors, or a descriptive sentence for envelope / lookup errors.
    """
    # 1. Envelope validation ------------------------------------------------
    msg_type = msg.get("type")
    if not msg_type:
        return ["Missing required field: type"]

    if msg_type not in VALID_TYPES:
        return [f"Unknown message type: {msg_type!r}"]

    # Protocol-version check (RFC-450 §8.1).  Enforced for envelope message
    # types; the three control types (connection_init/ping/pong) carry proto
    # but are validated leniently.
    if msg_type in _ENVELOPE_TYPES:
        proto = msg.get("proto")
        if proto != "1":
            return [f"Unsupported or missing protocol version: {proto!r}. Expected '1'."]

    # 2. Look up params schema by (type, method) ---------------------------
    method = msg.get("method")
    schema = PARAMS_REGISTRY.get((msg_type, method))

    if schema is None:
        # Unknown (type, method) — return METHOD_NOT_FOUND-style error.
        return [f"Unknown method {method!r} for type {msg_type!r}"]

    # 3. Validate params ----------------------------------------------------
    # In the protocol-1 envelope, operation fields live under ``params``;
    # the three control types carry fields at the top level. Validate
    # whichever dict carries the data (models use ``extra = "allow"``).
    params = msg.get("params")
    validation_target = params if isinstance(params, dict) else msg

    try:
        schema.model_validate(validation_target)
    except ValidationError as exc:
        return [f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()]

    return []


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
        encoded = json.dumps(msg, ensure_ascii=False)
        return len(encoded.encode("utf-8")) <= max_size_bytes
    except (TypeError, ValueError):
        return False
