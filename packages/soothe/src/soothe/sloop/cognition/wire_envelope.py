"""Envelope peeling for planner structured-output payloads (IG-668).

Thinking models sometimes emit the requested object nested under a single
wrapper key named after the prompt section (``{"PLAN_ASSESS": {...}}``) instead
of at the document root. The payload is otherwise valid, so peel the wrapper
before schema validation rather than discarding the response.
"""

from __future__ import annotations

from typing import Any

# Guard against pathological nesting while still peeling the common one- or
# two-level wrappers (e.g. section name around a schema-named object).
_MAX_ENVELOPE_DEPTH = 3


def unwrap_schema_envelope(data: Any, *, marker_key: str) -> Any:
    """Peel single-key wrappers until ``marker_key`` is present at the root.

    Args:
        data: Parsed structured-output payload.
        marker_key: Field that identifies an unwrapped payload (a required
            property of the target schema).

    Returns:
        The innermost dict containing ``marker_key``, or ``data`` unchanged when
        no such wrapper is present.
    """
    current = data
    for _ in range(_MAX_ENVELOPE_DEPTH):
        if not isinstance(current, dict) or marker_key in current or len(current) != 1:
            break
        inner = next(iter(current.values()))
        if not isinstance(inner, dict):
            break
        current = inner
    return current if isinstance(current, dict) and marker_key in current else data


__all__ = ["unwrap_schema_envelope"]
