"""Tests for the per-loop card manager (real-time binding + DB ledger)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_daemon.display.loop_card_manager import (
    CARD_CREATED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    LoopCardManager,
)


async def _seed_messages(
    manager: LoopCardManager,
    loop_id: str,
    messages: list,
    *,
    log_events: list[dict] | None = None,
) -> None:
    state = manager._buffers[loop_id]  # noqa: SLF001
    state.messages = list(messages)
    state.log_events = list(log_events or [])
    await manager._flush_buffers_to_ledger(loop_id, state)  # noqa: SLF001


@pytest.mark.asyncio
async def test_record_user_prompt_persists_user_card(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=None))
    await manager.record_user_prompt("loop_a", "hello")
    ledger = await manager.ensure_for_loop("loop_a")
    assert [card.content for card in ledger.snapshot()] == ["hello"]
    assert isolated_display_db.peek_user_prompt("loop_a") == "hello"


@pytest.mark.asyncio
async def test_bind_messages_from_checkpoint_messages() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(
        manager,
        "loop_b",
        [HumanMessage(content="from log"), AIMessage(content="log reply")],
    )
    ledger = await manager.ensure_for_loop("loop_b")
    assert [card.content for card in ledger.snapshot()] == ["from log", "log reply"]


@pytest.mark.asyncio
async def test_bind_messages_from_activity_log() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    activity = [
        {
            "kind": "conversation",
            "role": "user",
            "content": "from log",
            "timestamp": "2026-06-04T10:00:00+00:00",
        },
        {
            "kind": "conversation",
            "role": "assistant",
            "content": "log reply",
            "timestamp": "2026-06-04T10:00:01+00:00",
        },
    ]
    await _seed_messages(manager, "loop_c", [], log_events=activity)
    ledger = await manager.ensure_for_loop("loop_c")
    assert [card.content for card in ledger.snapshot()] == ["from log", "log reply"]


@pytest.mark.asyncio
async def test_ensure_for_loop_returns_empty_when_no_data(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=None))
    ledger = await manager.ensure_for_loop("loop_empty")
    assert ledger.card_count() == 0
    assert isolated_display_db.list_mutations("loop_empty")[0].op == "header"


@pytest.mark.asyncio
async def test_is_display_empty_uses_db_only() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    assert await manager.is_display_empty("loop_fast") is True


@pytest.mark.asyncio
async def test_replay_to_client_empty_loop() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=None))
    sent: list[dict] = []

    async def collect(frame: dict) -> None:
        sent.append(frame)

    total = await manager.replay_to_client("loop_fast_replay", collect)
    assert total == 0
    assert sent[0]["type"] == CARD_REPLAY_BEGIN
    assert sent[-1]["type"] == CARD_REPLAY_END
    assert sent[0]["total_cards"] == 0


@pytest.mark.asyncio
async def test_replay_to_client_emits_begin_created_end() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    messages = [
        HumanMessage(content="q"),
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "/x"}}],
        ),
        ToolMessage(
            content="contents",
            tool_call_id="tc1",
            name="read_file",
            status="success",
        ),
        AIMessage(content="here you go"),
    ]
    await _seed_messages(manager, "loop_d", messages)

    sent: list[dict] = []

    async def collect(frame: dict) -> None:
        sent.append(frame)

    total = await manager.replay_to_client("loop_d", collect)
    types = [frame["type"] for frame in sent]
    assert types[0] == CARD_REPLAY_BEGIN
    assert types[-1] == CARD_REPLAY_END
    middle = types[1:-1]
    assert all(item == CARD_CREATED for item in middle)
    assert len(middle) == total


@pytest.mark.asyncio
async def test_replay_to_client_reads_persisted_cards() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(
        manager,
        "loop_refresh",
        [HumanMessage(content="turn1"), AIMessage(content="final goal completion response")],
    )

    sent: list[dict] = []

    async def collect(frame: dict) -> None:
        sent.append(frame)

    await manager.replay_to_client("loop_refresh", collect)
    replay_texts = [
        str(frame.get("data", {}).get("content", ""))
        for frame in sent
        if frame.get("type") == CARD_CREATED
    ]
    assert any("final goal completion response" in text for text in replay_texts)


@pytest.mark.asyncio
async def test_stop_for_loop_releases_in_memory_state(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(manager, "loop_e", [HumanMessage(content="x")])
    assert "loop_e" in manager._ledgers  # noqa: SLF001

    await manager.stop_for_loop("loop_e")
    assert "loop_e" not in manager._ledgers  # noqa: SLF001
    assert isolated_display_db.list_mutations("loop_e")


@pytest.mark.asyncio
async def test_ensure_for_loop_without_runner_still_opens_ledger(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=None))
    ledger = await manager.ensure_for_loop("loop_no_runner")
    assert ledger.card_count() == 0
    assert isolated_display_db.list_mutations("loop_no_runner")


if __name__ == "__main__":  # pragma: no cover - convenience
    sys.exit(pytest.main([__file__, "-v"]))
