"""Tests for the file-backed loop card ledger (RFC-413)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

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
async def test_ensure_loaded_creates_header_on_fresh_directory(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    assert not ledger.path.exists()
    await ledger.ensure_loaded()
    assert ledger.path.exists()

    with ledger.path.open() as fh:
        first_line = fh.readline()
    parsed = json.loads(first_line)
    assert parsed["op"] == "header"
    assert parsed["seq"] == 0
    assert parsed["data"]["card_schema_version"] == CARD_SCHEMA_VERSION
    assert parsed["data"]["loop_id"] == "loop_a"
    assert ledger.next_seq() == 1
    assert ledger.card_count() == 0


@pytest.mark.asyncio
async def test_append_writes_jsonl_line_and_advances_seq(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()

    card = _user_card("hello")
    mutation = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id=card.id,
        kind=str(card.type),
        data=card_to_wire_dict(card),
    )
    await ledger.append(mutation)

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + create
    parsed = json.loads(lines[1])
    assert parsed["op"] == "create"
    assert parsed["card_id"] == card.id
    assert ledger.next_seq() == 2
    assert ledger.card_count() == 1


@pytest.mark.asyncio
async def test_append_many_batches_in_one_lock(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()

    cards = [_user_card(f"msg {i}") for i in range(5)]
    mutations = cards_to_mutations(cards)
    await ledger.append_many(mutations)

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 + 5
    assert ledger.card_count() == 5


@pytest.mark.asyncio
async def test_reload_restores_state_across_simulated_restart(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()

    cards = [_user_card("one"), _user_card("two"), _user_card("three")]
    await ledger.append_many(cards_to_mutations(cards))

    # Simulate restart: build a fresh ledger pointing at the same dir.
    reloaded = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await reloaded.ensure_loaded()

    snapshot = reloaded.snapshot()
    assert [c.content for c in snapshot] == ["one", "two", "three"]
    assert reloaded.next_seq() == 4


@pytest.mark.asyncio
async def test_malformed_line_is_skipped_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Hand-craft a file with a valid header + one garbage line + one valid create.
    file_path = tmp_path / "cards.jsonl"
    header = {
        "seq": 0,
        "ts": utc_now_iso(),
        "op": "header",
        "card_id": "__header__",
        "kind": "header",
        "data": {"card_schema_version": 1, "loop_id": "loop_a", "created_by": "test"},
    }
    valid_card = _user_card("survived")
    valid_create = CardMutation(
        seq=1,
        ts=utc_now_iso(),
        op="create",
        card_id=valid_card.id,
        kind=str(valid_card.type),
        data=card_to_wire_dict(valid_card),
    ).to_jsonl_dict()

    with file_path.open("w") as fh:
        fh.write(json.dumps(header) + "\n")
        fh.write("this is not json\n")
        fh.write(json.dumps(valid_create) + "\n")

    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    with caplog.at_level("WARNING"):
        await ledger.ensure_loaded()

    snapshot = ledger.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].content == "survived"
    assert any("malformed card ledger line" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_replace_with_resets_file_and_state(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()
    await ledger.append_many(cards_to_mutations([_user_card("stale")]))

    fresh_cards = [_user_card("new1"), _user_card("new2")]
    fresh_mutations = cards_to_mutations(fresh_cards)
    await ledger.replace_with(fresh_mutations)

    snapshot = ledger.snapshot()
    assert [c.content for c in snapshot] == ["new1", "new2"]

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    # Header + 2 cards (the "stale" one is gone).
    assert len(lines) == 3
    assert json.loads(lines[0])["op"] == "header"


@pytest.mark.asyncio
async def test_concurrent_appends_are_serialized(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()

    cards = [_user_card(f"concurrent {i}") for i in range(20)]
    mutations = cards_to_mutations(cards)

    # Drive 20 appends concurrently; lock should serialize.
    await asyncio.gather(*[ledger.append(m) for m in mutations])

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 + 20
    assert ledger.card_count() == 20

    # Seq values on disk should be a permutation of 1..20 with no duplicates.
    seqs = [json.loads(line)["seq"] for line in lines[1:]]
    assert sorted(seqs) == list(range(1, 21))


@pytest.mark.asyncio
async def test_tool_card_round_trips_status_and_output(tmp_path: Path) -> None:
    ledger = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await ledger.ensure_loaded()

    tool = _tool_card("read_file", status=ToolStatus.SUCCESS)
    tool.tool_output = "file contents"
    await ledger.append(
        CardMutation(
            seq=1,
            ts=utc_now_iso(),
            op="create",
            card_id=tool.id,
            kind=str(tool.type),
            data=card_to_wire_dict(tool),
        )
    )

    reloaded = LoopCardLedger(loop_id="loop_a", directory=tmp_path)
    await reloaded.ensure_loaded()
    snapshot = reloaded.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].type is MessageType.TOOL
    assert snapshot[0].tool_status is ToolStatus.SUCCESS
    assert snapshot[0].tool_output == "file contents"
