"""Shared event formatting logic for CLI and TUI modes.

Provides registry-driven event summary building.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.event_catalog import REGISTRY

logger = logging.getLogger(__name__)

# Default max length for terminal display (RFC-0020)
TERMINAL_WIDTH_DEFAULT = 120


def build_event_summary(event_type: str, data: dict[str, Any]) -> str:
    """Build human-readable summary from registry template.

    Args:
        event_type: Event type string.
        data: Event payload.

    Returns:
        Summary string or empty string if no template/error.
    """
    meta = REGISTRY.get_meta(event_type)
    if meta and meta.summary_template:
        try:
            payload = dict(data)
            # Agentic loop completion moved to completion_summary (avoid huge evidence blobs in UI).
            if event_type == "soothe.cognition.agent_loop.completed":
                payload.setdefault(
                    "completion_summary",
                    ((payload.get("evidence_summary") or "") or "complete").strip()[:240] or "complete",
                )
            return meta.summary_template.format(**payload)
        except (KeyError, ValueError) as e:
            logger.debug("Failed to format template for %s: %s", event_type, e)
            return ""
    return ""


def truncate_summary(summary: str, max_len: int = TERMINAL_WIDTH_DEFAULT) -> str:
    """Truncate summary to max length, preserving word boundaries.

    Args:
        summary: Summary text.
        max_len: Maximum length (default 80 for terminal width).

    Returns:
        Truncated summary with "..." suffix if needed.
    """
    if len(summary) <= max_len:
        return summary
    # Preserve word boundary
    return summary[: max_len - 3].rsplit(" ", 1)[0] + "..."


__all__ = [
    "TERMINAL_WIDTH_DEFAULT",
    "build_event_summary",
    "truncate_summary",
]
