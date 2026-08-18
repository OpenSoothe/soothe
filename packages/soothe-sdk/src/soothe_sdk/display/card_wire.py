"""Parse and apply daemon ``soothe.card.*`` wire frames (RFC-413).

Live frames arrive as ``event`` / ``mode=custom`` with ``data.type`` from
``soothe_sdk.core.events.CARD_*``. Clients apply them onto a card-id map;
UI hosts (TUI) additionally mount widgets from the same parse path.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.core.events import (
    CARD_CREATED,
    CARD_FINALIZED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    CARD_REPLAY_WIRE_TYPES,
    CARD_UPDATED,
    CARD_WIRE_TYPES,
)
from soothe_sdk.display.card_ledger import card_from_wire_dict, card_to_wire_dict
from soothe_sdk.display.transcript_types import MessageData

logger = logging.getLogger(__name__)

_ALL_CARD_FRAME_TYPES = frozenset(CARD_WIRE_TYPES | CARD_REPLAY_WIRE_TYPES)


def parse_card_custom_payload(
    data: Any,
) -> tuple[str, MessageData | None, dict[str, Any]] | None:
    """Parse a custom-mode card frame.

    Returns:
        ``(wire_type, full_card_or_none, update_patch)`` or ``None`` if not a
        card mutation frame (replay markers return with empty card/patch).
    """
    if not isinstance(data, dict):
        return None
    wire_type = str(data.get("type") or "").strip()
    if wire_type not in _ALL_CARD_FRAME_TYPES:
        return None
    if wire_type in CARD_REPLAY_WIRE_TYPES:
        return wire_type, None, {}

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


class CardProjection:
    """In-memory card_id → MessageData map driven by ``soothe.card.*`` frames."""

    def __init__(self) -> None:
        self._cards: dict[str, MessageData] = {}
        self._replaying = False

    @property
    def replaying(self) -> bool:
        """True while between ``replay.begin`` and ``replay.end``."""
        return self._replaying

    def snapshot(self) -> list[MessageData]:
        """Return cards in insertion order."""
        return list(self._cards.values())

    def get(self, card_id: str) -> MessageData | None:
        """Return one card by id, if present."""
        return self._cards.get(card_id)

    def apply(self, data: Any) -> bool:
        """Apply one custom-mode card payload. Returns True when handled."""
        parsed = parse_card_custom_payload(data)
        if parsed is None:
            return False
        wire_type, card, patch = parsed
        if wire_type == CARD_REPLAY_BEGIN:
            self._replaying = True
            self._cards.clear()
            return True
        if wire_type == CARD_REPLAY_END:
            self._replaying = False
            return True
        if wire_type == CARD_CREATED and card is not None:
            card_id = str(card.id or "").strip()
            if not card_id:
                return True
            self._cards[card_id] = card
            return True
        if wire_type in {CARD_UPDATED, CARD_FINALIZED}:
            card_id = str(patch.get("id") or "").strip()
            if not card_id:
                return True
            existing = self._cards.get(card_id)
            if existing is None:
                return True
            wire = card_to_wire_dict(existing)
            for key, value in patch.items():
                if key in {"id", "type"}:
                    continue
                wire[key] = value
            try:
                self._cards[card_id] = card_from_wire_dict(wire)
            except Exception:
                logger.debug("Invalid %s patch for %s", wire_type, card_id, exc_info=True)
            return True
        return True


__all__ = [
    "CARD_CREATED",
    "CARD_FINALIZED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "CARD_REPLAY_WIRE_TYPES",
    "CARD_UPDATED",
    "CARD_WIRE_TYPES",
    "CardProjection",
    "parse_card_custom_payload",
]
