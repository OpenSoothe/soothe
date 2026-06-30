"""Tests for the SQLite-backed loop card ledger."""

from __future__ import annotations

import pytest
from soothe_sdk.display.card_ledger import (
    CARD_SCHEMA_VERSION,
    CardMutation,
    card_to_wire_dict,
    cards_to_mutations,
    utc_now_iso,
)
from soothe_sdk.display.transcript_types import (
    MessageData,
    MessageType,
    ToolStatus,
)

from soothe_daemon.display.loop_card_ledger import LoopCardLedger


def _user_card(text: str) -> MessageData:
    return MessageData(type=MessageType.USER, content=text)


def _tool_card(name: str, *, status: ToolStatus = ToolStatus.PENDING) -> MessageData:
    return MessageData(
        type=MessageType.TOOL,
        content="",
        tool_name=name,
        tool_status=status,
    )


@pytest.mark.asyncio
async def test_ensure_loaded_creates_header_in_display_db(isolated_display_db) -> None:
    ledger = LoopCardLedger(loop_id="loop_a")
    await ledger.ensure_loaded()
    mutations = isolated_display_db.list_mutations("loop_a")
    assert mutations
    assert mutations[0].op == "header"
    assert mutations[0].seq == 0
    assert mutations[0].data["card_schema_version"] == CARD_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_append_persists_create_mutation(isolated_display_db) -> None:
    ledger = LoopCardLedger(loop_id="loop_b")
    await ledger.ensure_loaded()
    mutation = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id="card_user_1",
        kind="user",
        data=card_to_wire_dict(_user_card("hello")),
    )
    await ledger.append(mutation)
    stored = isolated_display_db.list_mutations("loop_b")
    assert any(row.op == "create" and row.card_id == "card_user_1" for row in stored)


@pytest.mark.asyncio
async def test_append_many_round_trips_snapshot() -> None:
    ledger = LoopCardLedger(loop_id="loop_c")
    cards = [_user_card("one"), _user_card("two")]
    await ledger.append_many(cards_to_mutations(cards))
    snapshot = ledger.snapshot()
    assert [card.content for card in snapshot] == ["one", "two"]


@pytest.mark.asyncio
async def test_replace_with_rewrites_db_rows(isolated_display_db) -> None:
    ledger = LoopCardLedger(loop_id="loop_d")
    await ledger.append_many(cards_to_mutations([_user_card("stale")]))
    fresh_cards = [_user_card("fresh")]
    await ledger.replace_with(cards_to_mutations(fresh_cards))
    snapshot = ledger.snapshot()
    assert [card.content for card in snapshot] == ["fresh"]
    stored = [row for row in isolated_display_db.list_mutations("loop_d") if row.op == "create"]
    assert len(stored) == 1
    assert stored[0].data["content"] == "fresh"


@pytest.mark.asyncio
async def test_to_mutations_snapshot_matches_card_count() -> None:
    ledger = LoopCardLedger(loop_id="loop_e")
    cards = [_user_card("q"), _tool_card("read_file")]
    await ledger.replace_with(cards_to_mutations(cards))
    mutations = ledger.to_mutations_snapshot()
    assert len(mutations) == 2
    assert mutations[0].kind == "user"
    assert mutations[1].kind == "tool"


@pytest.mark.asyncio
async def test_inconsistent_mutation_is_dropped_on_load(isolated_display_db) -> None:
    header = CardMutation(
        seq=0,
        ts=utc_now_iso(),
        op="header",
        card_id="__header__",
        kind="header",
        data={"card_schema_version": CARD_SCHEMA_VERSION, "loop_id": "loop_f", "created_by": "x"},
    )
    valid_create = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id="card_ok",
        kind="user",
        data=card_to_wire_dict(_user_card("ok")),
    )
    invalid_update = CardMutation(
        seq=2,
        ts=utc_now_iso(),
        op="update",
        card_id="missing",
        kind="user",
        data={"content": "nope"},
    )
    isolated_display_db.replace_mutations("loop_f", [header, valid_create, invalid_update])
    ledger = LoopCardLedger(loop_id="loop_f")
    await ledger.ensure_loaded()
    assert ledger.card_count() == 1
    assert ledger.snapshot()[0].content == "ok"
