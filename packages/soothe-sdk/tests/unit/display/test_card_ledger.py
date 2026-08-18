"""Tests for the pure-Python card ledger primitives (RFC-413)."""

from __future__ import annotations

import pytest

from soothe_sdk.display.card_ledger import (
    CARD_SCHEMA_VERSION,
    CardMutation,
    InMemoryCardLedger,
    build_header_mutation,
    card_from_wire_dict,
    card_to_wire_dict,
    cards_to_mutations,
    utc_now_iso,
)
from soothe_sdk.display.transcript_types import (
    MessageData,
    MessageType,
    ToolStatus,
)


def test_card_to_wire_dict_and_back_round_trips_enums() -> None:
    original = MessageData(
        type=MessageType.TOOL,
        content="",
        tool_name="read_file",
        tool_status=ToolStatus.SUCCESS,
        tool_output="ok",
    )
    wire = card_to_wire_dict(original)
    assert wire["type"] == "tool"
    assert wire["tool_status"] == "success"
    rebuilt = card_from_wire_dict(wire)
    assert rebuilt.type is MessageType.TOOL
    assert rebuilt.tool_status is ToolStatus.SUCCESS
    assert rebuilt.tool_name == "read_file"
    assert rebuilt.tool_output == "ok"


def test_build_header_mutation_carries_version() -> None:
    header = build_header_mutation(loop_id="loop_abc", created_by="test")
    assert header.seq == 0
    assert header.op == "header"
    assert header.data["card_schema_version"] == CARD_SCHEMA_VERSION
    assert header.data["loop_id"] == "loop_abc"
    assert header.data["created_by"] == "test"


def test_apply_header_then_create_advances_seq() -> None:
    ledger = InMemoryCardLedger()
    ledger.apply(build_header_mutation(loop_id="loop_abc", created_by="test"))
    assert ledger.next_seq == 1
    assert ledger.loop_id == "loop_abc"

    card = MessageData(type=MessageType.USER, content="hi")
    create = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id=card.id,
        kind=str(card.type),
        data=card_to_wire_dict(card),
    )
    ledger.apply(create)
    assert ledger.card_count() == 1
    assert ledger.next_seq == 2
    snapshot = ledger.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].content == "hi"
    assert snapshot[0].type is MessageType.USER


def test_apply_update_merges_only_updatable_fields() -> None:
    ledger = InMemoryCardLedger()
    card = MessageData(
        type=MessageType.TOOL,
        content="",
        tool_name="read_file",
        tool_status=ToolStatus.PENDING,
    )
    ledger.apply(
        CardMutation(
            seq=1,
            ts=utc_now_iso(),
            op="create",
            card_id=card.id,
            kind=str(card.type),
            data=card_to_wire_dict(card),
        )
    )
    ledger.apply(
        CardMutation(
            seq=2,
            ts=utc_now_iso(),
            op="update",
            card_id=card.id,
            kind=str(card.type),
            # tool_output is updatable; type / id should be ignored even if sent.
            data={"tool_output": "done", "type": "user", "id": "evil"},
        )
    )
    updated = ledger.get(card.id)
    assert updated is not None
    assert updated.tool_output == "done"
    # Identity fields preserved (update silently ignored them).
    assert updated.id == card.id
    assert updated.type is MessageType.TOOL


def test_apply_finalize_marks_terminal_state() -> None:
    ledger = InMemoryCardLedger()
    card = MessageData(
        type=MessageType.TOOL,
        content="",
        tool_name="read_file",
        tool_status=ToolStatus.RUNNING,
    )
    ledger.apply(
        CardMutation(
            seq=1,
            ts=utc_now_iso(),
            op="create",
            card_id=card.id,
            kind=str(card.type),
            data=card_to_wire_dict(card),
        )
    )
    ledger.apply(
        CardMutation(
            seq=2,
            ts=utc_now_iso(),
            op="finalize",
            card_id=card.id,
            kind=str(card.type),
            data={"tool_status": ToolStatus.SUCCESS.value, "tool_output": "ok"},
        )
    )
    final = ledger.get(card.id)
    assert final is not None
    assert final.tool_status == ToolStatus.SUCCESS.value
    assert final.tool_output == "ok"


def test_apply_update_on_unknown_card_raises() -> None:
    ledger = InMemoryCardLedger()
    with pytest.raises(ValueError, match="cannot apply op='update'"):
        ledger.apply(
            CardMutation(
                seq=1,
                ts=utc_now_iso(),
                op="update",
                card_id="msg-doesnotexist",
                kind="user",
                data={"content": "hi"},
            )
        )


def test_apply_unknown_op_raises() -> None:
    ledger = InMemoryCardLedger()
    with pytest.raises(ValueError, match="unknown card mutation op"):
        ledger.apply(
            CardMutation(
                seq=1,
                ts=utc_now_iso(),
                op="garbage",  # type: ignore[arg-type]
                card_id="msg-x",
                kind="user",
                data={},
            )
        )


def test_cards_to_mutations_then_from_mutations_round_trip() -> None:
    cards = [
        MessageData(type=MessageType.USER, content="first"),
        MessageData(type=MessageType.ASSISTANT, content="second"),
        MessageData(
            type=MessageType.TOOL,
            content="",
            tool_name="read_file",
            tool_status=ToolStatus.SUCCESS,
            tool_output="contents",
        ),
    ]
    mutations = cards_to_mutations(cards)
    assert [m.seq for m in mutations] == [1, 2, 3]
    assert {m.op for m in mutations} == {"create"}

    rebuilt = InMemoryCardLedger.from_mutations(mutations)
    snapshot = rebuilt.snapshot()
    assert len(snapshot) == 3
    assert snapshot[0].content == "first"
    assert snapshot[2].tool_output == "contents"
    assert snapshot[2].tool_status is ToolStatus.SUCCESS


def test_snapshot_preserves_insertion_order_across_updates() -> None:
    ledger = InMemoryCardLedger()
    cards = [
        MessageData(type=MessageType.USER, content="one"),
        MessageData(type=MessageType.USER, content="two"),
        MessageData(type=MessageType.USER, content="three"),
    ]
    for offset, card in enumerate(cards):
        ledger.apply(
            CardMutation(
                seq=offset + 1,
                ts=utc_now_iso(),
                op="create",
                card_id=card.id,
                kind=str(card.type),
                data=card_to_wire_dict(card),
            )
        )
    # Update middle card; order must not change.
    ledger.apply(
        CardMutation(
            seq=4,
            ts=utc_now_iso(),
            op="update",
            card_id=cards[1].id,
            kind=str(cards[1].type),
            data={"content": "TWO-updated"},
        )
    )
    snapshot = ledger.snapshot()
    assert [c.content for c in snapshot] == ["one", "TWO-updated", "three"]


def test_jsonl_dict_round_trip_preserves_fields() -> None:
    mutation = CardMutation(
        seq=7,
        ts="2026-06-04T10:00:00+00:00",
        op="create",
        card_id="msg-abc",
        kind="user",
        data={"type": "user", "content": "hi"},
    )
    raw = mutation.to_jsonl_dict()
    rebuilt = CardMutation.from_jsonl_dict(raw)
    assert rebuilt == mutation


def test_from_mutations_replays_header_and_advances_seq() -> None:
    header = build_header_mutation(loop_id="loop_xyz", created_by="test")
    card = MessageData(type=MessageType.USER, content="hi")
    create = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id=card.id,
        kind=str(card.type),
        data=card_to_wire_dict(card),
    )
    ledger = InMemoryCardLedger.from_mutations([header, create], loop_id="loop_xyz")
    assert ledger.loop_id == "loop_xyz"
    assert ledger.next_seq == 2
    assert ledger.card_count() == 1
