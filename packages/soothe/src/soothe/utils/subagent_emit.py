"""Emit curated ``soothe.subagent.*`` wire events with truncation (IG-338)."""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.core.subagent_wire import clip_wire_event_payload, is_allowlisted_subagent_event_type

from soothe.utils.progress import emit_progress


def emit_subagent_wire_event(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit allowlisted subagent progress to LangGraph ``custom`` stream.

    Unknown types are dropped (must use constants from ``soothe_sdk.core.subagent_wire``).

    Args:
        event: Dict with at least ``type`` matching ``ALLOWLISTED_SUBAGENT_EVENT_TYPES``.
        logger: Caller logger for audit trail.
    """
    et = event.get("type", "")
    if not isinstance(et, str) or not is_allowlisted_subagent_event_type(et):
        logger.debug("Ignoring non-allowlisted subagent wire event: %r", et)
        return
    emit_progress(clip_wire_event_payload(event), logger)


__all__ = ["emit_subagent_wire_event"]
