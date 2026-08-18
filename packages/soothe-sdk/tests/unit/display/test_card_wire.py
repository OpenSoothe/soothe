"""Tests for ``soothe_sdk.display.card_wire`` (soothe.card.* projection)."""

from __future__ import annotations

from soothe_sdk.core.events import (
    CARD_CREATED,
    CARD_FINALIZED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    CARD_UPDATED,
)
from soothe_sdk.display.card_wire import CardProjection, parse_card_custom_payload


def test_parse_card_created() -> None:
    parsed = parse_card_custom_payload(
        {
            "type": CARD_CREATED,
            "card_id": "u1",
            "kind": "user",
            "data": {"type": "user", "content": "hi", "id": "u1"},
        }
    )
    assert parsed is not None
    wire_type, card, _patch = parsed
    assert wire_type == CARD_CREATED
    assert card is not None
    assert card.content == "hi"
    assert card.id == "u1"


def test_parse_card_updated_patch() -> None:
    parsed = parse_card_custom_payload(
        {
            "type": CARD_UPDATED,
            "card_id": "a1",
            "kind": "assistant",
            "data": {"content": "hello", "is_streaming": False},
        }
    )
    assert parsed is not None
    wire_type, card, patch = parsed
    assert wire_type == CARD_UPDATED
    assert card is None
    assert patch["content"] == "hello"
    assert patch["id"] == "a1"


def test_parse_ignores_non_card_custom() -> None:
    assert parse_card_custom_payload({"type": "soothe.cognition.intent.classified"}) is None


def test_parse_rejects_legacy_bare_card_type() -> None:
    assert parse_card_custom_payload({"type": "card.created", "data": {}}) is None


def test_card_projection_create_update_finalize() -> None:
    proj = CardProjection()
    assert proj.apply(
        {
            "type": CARD_CREATED,
            "card_id": "a1",
            "data": {"type": "assistant", "content": "hel", "id": "a1"},
        }
    )
    assert proj.get("a1") is not None
    assert proj.get("a1").content == "hel"  # type: ignore[union-attr]
    assert proj.apply(
        {
            "type": CARD_UPDATED,
            "card_id": "a1",
            "data": {"content": "hello"},
        }
    )
    assert proj.get("a1").content == "hello"  # type: ignore[union-attr]
    assert proj.apply({"type": CARD_FINALIZED, "card_id": "a1", "data": {}})
    assert [c.id for c in proj.snapshot()] == ["a1"]


def test_card_projection_replay_clears_and_loads() -> None:
    proj = CardProjection()
    proj.apply(
        {
            "type": CARD_CREATED,
            "card_id": "old",
            "data": {"type": "user", "content": "x", "id": "old"},
        }
    )
    assert proj.apply({"type": CARD_REPLAY_BEGIN})
    assert proj.replaying is True
    assert proj.snapshot() == []
    proj.apply(
        {
            "type": CARD_CREATED,
            "card_id": "new",
            "data": {"type": "user", "content": "y", "id": "new"},
        }
    )
    assert proj.apply({"type": CARD_REPLAY_END})
    assert proj.replaying is False
    assert [c.id for c in proj.snapshot()] == ["new"]
