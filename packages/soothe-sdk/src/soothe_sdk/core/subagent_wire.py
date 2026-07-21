"""Curated ``soothe.subagent.*`` wire protocol (metadata-only).

Provides registration, structural validation, payload clipping, and stream emission.
Event type strings live in each subagent (or plugin) ``events`` module — not in this SDK.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_REGISTERED_SUBAGENT_WIRE_TYPES: set[str] = set()

# ``soothe.subagent.<agent>.<signal>`` — clients may accept before producers register types.
_CURATED_SUBAGENT_WIRE_RE = re.compile(r"^soothe\.subagent\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]+$")

_DEFAULT_PREVIEW_LEN = 120
_LONG_PREVIEW_LEN = 200
_TASK_DESCRIPTION_LEN = 8000


def register_subagent_wire_event_types(*event_types: str) -> None:
    """Register ``soothe.subagent.*`` wire types for emission allowlisting.

    Subagents call this from their ``events`` module (or rely on the host
    event registry to register automatically).
    """
    for et in event_types:
        if isinstance(et, str) and et.startswith("soothe.subagent."):
            _REGISTERED_SUBAGENT_WIRE_TYPES.add(et)


def get_allowlisted_subagent_event_types() -> frozenset[str]:
    """Return wire types registered for emission in this process."""
    return frozenset(_REGISTERED_SUBAGENT_WIRE_TYPES)


def is_curated_subagent_wire_event_type(event_type: str) -> bool:
    """Return True for structurally valid curated ``soothe.subagent.*`` wire types.

    Used by CLI/TUI clients that may not import subagent ``events`` modules.
    """
    return bool(_CURATED_SUBAGENT_WIRE_RE.match(event_type))


def is_emit_allowed_subagent_wire_event_type(event_type: str) -> bool:
    """Return True when a producer may emit this subagent wire event."""
    return event_type in _REGISTERED_SUBAGENT_WIRE_TYPES


def is_allowlisted_subagent_event_type(event_type: str) -> bool:
    """Return True when a consumer may treat ``event_type`` as curated subagent wire."""
    return is_emit_allowed_subagent_wire_event_type(
        event_type
    ) or is_curated_subagent_wire_event_type(event_type)


def parse_subagent_wire_agent(event_type: str) -> str | None:
    """Return agent segment (``browser``, ``claude``, …) from ``soothe.subagent.<agent>.…``."""
    parts = event_type.split(".")
    if len(parts) >= 4 and parts[0] == "soothe" and parts[1] == "subagent":
        return parts[2]
    return None


def truncate_wire_str(value: str, max_len: int = _DEFAULT_PREVIEW_LEN) -> str:
    """Truncate a single wire string field."""
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return "…"
    return value[: max_len - 1] + "…"


def clip_wire_event_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Copy event dict and truncate known string fields for wire safety."""
    out = dict(data)
    string_caps: dict[str, int] = {
        "task_preview": _LONG_PREVIEW_LEN,
        "topic": _LONG_PREVIEW_LEN,
        "topic_preview": _DEFAULT_PREVIEW_LEN,
        "search_target": _TASK_DESCRIPTION_LEN,
        "task": _LONG_PREVIEW_LEN,
        "judgement": _LONG_PREVIEW_LEN,
        "message": _LONG_PREVIEW_LEN,
        "error": _LONG_PREVIEW_LEN,
        "action_preview": _DEFAULT_PREVIEW_LEN,
        "tool_name": _DEFAULT_PREVIEW_LEN,
        "input_preview": _DEFAULT_PREVIEW_LEN,
        "summary": _LONG_PREVIEW_LEN,
        "url": _LONG_PREVIEW_LEN,
        "title": _DEFAULT_PREVIEW_LEN,
        "query_preview": _DEFAULT_PREVIEW_LEN,
        "args_preview": _DEFAULT_PREVIEW_LEN,
        "result_preview": _DEFAULT_PREVIEW_LEN,
    }
    for key, cap in string_caps.items():
        val = out.get(key)
        if isinstance(val, str):
            out[key] = truncate_wire_str(val, cap)
    return out


def emit_subagent_wire_event(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit allowlisted subagent progress to the LangGraph ``custom`` stream.

    Community subagents use this helper so they do not depend on the host package.
    Unknown event types are dropped unless registered via :func:`register_subagent_wire_event_types`.

    Args:
        event: Dict with at least ``type`` registered for emission.
        logger: Caller logger for audit trail.
    """
    et = event.get("type", "")
    if not isinstance(et, str) or not is_emit_allowed_subagent_wire_event_type(et):
        logger.debug("Ignoring non-allowlisted subagent wire event: %r", et)
        return
    clipped = clip_wire_event_payload(event)
    logger.debug("subagent.wire %s", clipped.get("type", ""))
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(clipped)
    except (ImportError, RuntimeError, KeyError):
        pass


__all__ = [
    "clip_wire_event_payload",
    "emit_subagent_wire_event",
    "get_allowlisted_subagent_event_types",
    "is_allowlisted_subagent_event_type",
    "is_curated_subagent_wire_event_type",
    "is_emit_allowed_subagent_wire_event_type",
    "parse_subagent_wire_agent",
    "register_subagent_wire_event_types",
    "truncate_wire_str",
]
