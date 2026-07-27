"""Tests for TUI card wire helpers (IG-655)."""

from __future__ import annotations

from soothe_sdk.core.events import CARD_CREATED, CARD_UPDATED

from soothe_cli.tui.card_wire import parse_card_custom_payload


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
