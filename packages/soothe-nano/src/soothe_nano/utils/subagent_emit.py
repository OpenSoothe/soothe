"""Emit curated ``soothe.subagent.*`` wire events with truncation (IG-338)."""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.core.subagent_wire import (
    clip_wire_event_payload,
    is_emit_allowed_subagent_wire_event_type,
)

from soothe_nano.utils.progress import emit_progress


def emit_subagent_wire_event(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit allowlisted subagent progress to LangGraph ``custom`` stream.

    Delegates wire allowlisting and clipping to ``soothe_sdk``, then uses
    ``emit_progress`` so step context and compact logging match core agents.

    Unknown types are dropped (types must be registered via the subagent ``events`` module).

    Args:
        event: Dict with ``type`` registered for emission (see ``register_event``).
        logger: Caller logger for audit trail.
    """
    et = event.get("type", "")
    if not isinstance(et, str):
        logger.debug("Ignoring subagent wire event without string type: %r", et)
        return
    if not is_emit_allowed_subagent_wire_event_type(et):
        logger.debug("Ignoring non-allowlisted subagent wire event: %r", et)
        return

    emit_progress(clip_wire_event_payload(event), logger)


__all__ = ["emit_subagent_wire_event"]
