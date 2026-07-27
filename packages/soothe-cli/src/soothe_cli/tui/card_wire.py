"""Apply daemon ``card.*`` wire frames to the TUI (RFC-413 / IG-655).

Live frames arrive as ``event`` / ``mode=custom`` with ``data.type`` from
``soothe_sdk.core.events.CARD_*``. Structural cards (user, assistant,
cognition, …) mount from that projection; raw stream handlers still drive
live step tool-row updates onto step widgets registered from ``card.*``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.core.events import (
    CARD_CREATED,
    CARD_FINALIZED,
    CARD_UPDATED,
    CARD_WIRE_TYPES,
)
from soothe_sdk.display.card_ledger import card_from_wire_dict
from soothe_sdk.display.transcript_types import MessageData

logger = logging.getLogger(__name__)


def parse_card_custom_payload(data: Any) -> tuple[str, MessageData | None, dict[str, Any]] | None:
    """Parse a custom-mode card frame.

    Returns:
        ``(wire_type, full_card_or_none, update_patch)`` or ``None`` if not a
        card frame.
    """
    if not isinstance(data, dict):
        return None
    wire_type = str(data.get("type") or "").strip()
    if wire_type not in CARD_WIRE_TYPES:
        return None
    payload = data.get("data")
    if not isinstance(payload, dict):
        payload = {}
    card_id = str(data.get("card_id") or payload.get("id") or "").strip()
    if wire_type == CARD_CREATED:
        try:
            if "type" in payload and "content" in payload:
                card = card_from_wire_dict(payload)
            else:
                return None
        except Exception:
            logger.debug("Invalid %s payload", CARD_CREATED, exc_info=True)
            return None
        return wire_type, card, {}

    patch = dict(payload)
    if card_id and "id" not in patch:
        patch["id"] = card_id
    return wire_type, None, patch


__all__ = [
    "CARD_CREATED",
    "CARD_FINALIZED",
    "CARD_UPDATED",
    "CARD_WIRE_TYPES",
    "parse_card_custom_payload",
]
