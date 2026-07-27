"""Tests for the per-loop card manager (real-time binding + DB ledger)."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from soothe_sdk.core.events import (
    CARD_CREATED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    CARD_UPDATED,
)

from soothe_daemon.display.loop_card_manager import (
    LoopCardManager,
    _BindingBuffers,
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
async def test_peek_latest_assistant_response_returns_latest_card(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(
        manager,
        "loop_latest_ai",
        [
            HumanMessage(content="question"),
            AIMessage(content="first answer"),
            AIMessage(content="latest answer"),
        ],
    )
    assert isolated_display_db.peek_latest_assistant_response("loop_latest_ai") == "latest answer"


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
async def test_live_cognition_custom_events_bind_to_ledger(isolated_display_db) -> None:
    """Flat live ``soothe.cognition.*`` customs must project intent/plan cards."""
    manager = LoopCardManager(
        SimpleNamespace(_runner=MagicMock()),
        flush_debounce_ms=0,
    )
    await manager.ingest_stream_tuple(
        "loop_cognition",
        (),
        "custom",
        {
            "type": "soothe.cognition.intent.classified",
            "reasoning": "I'll map the repository layout first.",
            "intent_type": "agentic",
        },
    )
    await manager.ingest_stream_tuple(
        "loop_cognition",
        (),
        "custom",
        {
            "type": "soothe.cognition.strange_loop.reasoned",
            "status": "continue",
            "iteration": 1,
            "plan_action": "new",
            "assessment_reasoning": "Need structure discovery.",
            "plan_reasoning": "Scan packages and config, then summarize architecture.",
        },
    )
    await asyncio.sleep(0.05)
    ledger = await manager.ensure_for_loop("loop_cognition")
    cards = ledger.snapshot()
    reason_cards = [c for c in cards if c.type.value == "cognition_reason"]
    assert len(reason_cards) >= 2
    texts = " ".join(
        f"{c.cognition_plan_strategy or ''} {c.cognition_plan_assessment or ''}"
        for c in reason_cards
    )
    assert "map the repository" in texts
    assert "Scan packages" in texts or "structure discovery" in texts
    await manager.stop_for_loop("loop_cognition")


@pytest.mark.asyncio
async def test_debounced_flush_coalesces_rapid_ingests(monkeypatch) -> None:
    """Multiple stream frames within the debounce window produce one bind pass (IG-546)."""
    manager = LoopCardManager(
        SimpleNamespace(_runner=MagicMock()),
        flush_debounce_ms=100,
    )
    flush_count = 0
    original_flush = manager._flush_buffers_to_ledger

    async def counting_flush(loop_id: str, state: _BindingBuffers) -> None:
        nonlocal flush_count
        flush_count += 1
        await original_flush(loop_id, state)

    monkeypatch.setattr(manager, "_flush_buffers_to_ledger", counting_flush)

    custom = {"kind": "conversation", "role": "assistant", "content": "a"}
    for _ in range(8):
        await manager.ingest_stream_tuple("loop_debounce", (), "custom", dict(custom))
    await asyncio.sleep(0.05)
    assert flush_count == 0
    await asyncio.sleep(0.15)
    assert flush_count == 1
    await manager.stop_for_loop("loop_debounce")


@pytest.mark.asyncio
async def test_ingest_stream_tuple_returns_before_flush_completes(monkeypatch) -> None:
    """Stream ingest must not block on ledger flush (IG-534 §2.3)."""
    manager = LoopCardManager(
        SimpleNamespace(_runner=MagicMock()),
        flush_debounce_ms=50,
    )
    flush_started = asyncio.Event()

    original_flush = manager._flush_buffers_to_ledger

    async def slow_flush(loop_id: str, state: _BindingBuffers) -> None:
        flush_started.set()
        await asyncio.sleep(0.15)
        await original_flush(loop_id, state)

    monkeypatch.setattr(manager, "_flush_buffers_to_ledger", slow_flush)

    wire = {"type": "ai", "content": "hello", "chunk_position": "last"}
    await manager.ingest_stream_tuple("loop_async", (), "messages", (wire, {}))
    assert not flush_started.is_set()
    await asyncio.wait_for(flush_started.wait(), timeout=1.0)
    await asyncio.sleep(0.2)
    ledger = await manager.ensure_for_loop("loop_async")
    assert ledger.card_count() >= 1
    await manager.stop_for_loop("loop_async")


@pytest.mark.asyncio
async def test_stop_for_loop_releases_in_memory_state(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(manager, "loop_e", [HumanMessage(content="x")])
    assert "loop_e" in manager._ledgers  # noqa: SLF001

    await manager.stop_for_loop("loop_e")
    assert "loop_e" not in manager._ledgers  # noqa: SLF001
    assert isolated_display_db.list_mutations("loop_e")


@pytest.mark.asyncio
async def test_ingest_overflow_preserves_frames(monkeypatch) -> None:
    """Overflow deque must not drop frames when the bounded queue is full (IG-546)."""
    manager = LoopCardManager(
        SimpleNamespace(_runner=MagicMock()),
        ingest_queue_maxsize=2,
        flush_debounce_ms=0,
    )
    processed: list[Any] = []
    original = manager._ingest_stream_tuple_now

    async def record(loop_id: str, namespace, mode, data) -> None:
        processed.append(data)
        await original(loop_id, namespace, mode, data)

    monkeypatch.setattr(manager, "_ingest_stream_tuple_now", record)

    custom = {"kind": "conversation", "role": "assistant", "content": "x"}
    for i in range(5):
        await manager.ingest_stream_tuple(
            "loop_overflow",
            (),
            "custom",
            {**custom, "content": f"msg-{i}"},
        )
    await asyncio.sleep(0.3)
    assert len(processed) == 5
    worker = manager._ingest_workers.get("loop_overflow")  # noqa: SLF001
    assert worker is not None
    assert len(worker.overflow) == 0
    await manager.stop_for_loop("loop_overflow")


@pytest.mark.asyncio
async def test_overflow_emits_stream_degraded(monkeypatch) -> None:
    """First overflow frame notifies clients via stream_degraded (RFC-450 §14)."""
    from soothe_daemon.display.loop_card_manager import (
        reset_card_ingest_overflow_metrics,
    )

    reset_card_ingest_overflow_metrics()
    broadcasts: list[dict] = []

    async def capture(msg: dict) -> None:
        broadcasts.append(msg)

    manager = LoopCardManager(
        SimpleNamespace(_broadcast=capture),
        ingest_queue_maxsize=1,
        flush_debounce_ms=0,
    )
    custom = {"kind": "conversation", "role": "assistant", "content": "a"}
    await manager.ingest_stream_tuple("loop_sd", (), "custom", dict(custom))
    await manager.ingest_stream_tuple("loop_sd", (), "custom", {**custom, "content": "b"})
    await asyncio.sleep(0.05)
    assert any(
        m.get("mode") == "custom" and (m.get("data") or {}).get("type") == "stream_degraded"
        for m in broadcasts
    )
    await manager.stop_for_loop("loop_sd")
    reset_card_ingest_overflow_metrics()


@pytest.mark.asyncio
async def test_stop_for_loop_cancels_ingest_worker() -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await manager.ingest_stream_tuple(
        "loop_worker",
        (),
        "custom",
        {"kind": "conversation", "role": "assistant", "content": "hi"},
    )
    assert "loop_worker" in manager._ingest_workers  # noqa: SLF001
    await manager.stop_for_loop("loop_worker")
    assert "loop_worker" not in manager._ingest_workers  # noqa: SLF001


@pytest.mark.asyncio
async def test_ensure_for_loop_without_runner_still_opens_ledger(isolated_display_db) -> None:
    manager = LoopCardManager(SimpleNamespace(_runner=None))
    ledger = await manager.ensure_for_loop("loop_no_runner")
    assert ledger.card_count() == 0
    assert isolated_display_db.list_mutations("loop_no_runner")


@pytest.mark.asyncio
async def test_freeze_goal_display_prefers_goal_completion_phase_text(
    isolated_display_db,
) -> None:
    """RFC-631 freeze must use goal_completion wire text, not mixed full_response."""
    from langchain_core.messages import AIMessage, HumanMessage

    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(
        manager,
        "loop_gc",
        [
            HumanMessage(content="count files"),
            AIMessage(
                content="**Total file count in packages: 3632**",
                phase="goal_completion",
            ),
            AIMessage(
                content="I'll count all files in the packages directory.",
                phase="plan_direct",
            ),
        ],
    )
    await manager.freeze_goal_display(
        "loop_gc",
        goal_id="goal_0",
        goal_text="count files",
        goal_completion="**Total file count in packages: 3632**",
    )
    snapshots = isolated_display_db.list_goal_snapshots("loop_gc")
    assert len(snapshots) == 1
    assert snapshots[0]["goal_completion"] == "**Total file count in packages: 3632**"
    assistants = [c for c in snapshots[0].get("display_cards", []) if c.get("type") == "assistant"]
    assert len(assistants) == 2


@pytest.mark.asyncio
async def test_freeze_goal_display_snapshots_current_user_segment_only(
    isolated_display_db,
) -> None:
    """RFC-631: freeze must not bleed prior goal cards into the new snapshot."""
    manager = LoopCardManager(SimpleNamespace(_runner=MagicMock()))
    await _seed_messages(
        manager,
        "loop_freeze",
        [
            HumanMessage(content="how are u"),
            AIMessage(content="Hey there!"),
            HumanMessage(content="shanghai weather"),
            AIMessage(content="It is rainy."),
        ],
    )
    await manager.freeze_goal_display(
        "loop_freeze",
        goal_id="goal_1",
        goal_text="shanghai weather",
        goal_completion="It is rainy.",
    )
    snapshots = isolated_display_db.list_goal_snapshots("loop_freeze")
    assert len(snapshots) == 1
    assistant_text = " ".join(
        c.get("content", "")
        for c in snapshots[0].get("display_cards", [])
        if c.get("type") == "assistant"
    )
    assert "Hey there!" not in assistant_text
    assert "rainy" in assistant_text
    state = manager._buffers.get("loop_freeze")  # noqa: SLF001
    assert state is not None
    assert state.messages == []
    assert state.log_events == []


@pytest.mark.asyncio
async def test_second_flush_appends_update_and_broadcasts_card_frames(
    isolated_display_db,
) -> None:
    """IG-655: subsequent binds append updates instead of replace_with wipe."""
    broadcasted: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasted.append(msg)

    daemon = SimpleNamespace(_runner=MagicMock(), _broadcast=_broadcast)
    manager = LoopCardManager(daemon)

    await _seed_messages(
        manager,
        "loop_append",
        [HumanMessage(content="q"), AIMessage(content="hel")],
    )
    first_count = len(isolated_display_db.list_mutations("loop_append"))
    assert first_count >= 2  # header + creates

    # Grow assistant content — stable asst ordinal key should emit update.
    await _seed_messages(
        manager,
        "loop_append",
        [HumanMessage(content="q"), AIMessage(content="hello world")],
    )
    mutations = isolated_display_db.list_mutations("loop_append")
    ops = [m.op for m in mutations]
    assert "update" in ops
    assert ops.count("header") == 1

    card_frames = [
        f
        for f in broadcasted
        if f.get("type") == "event"
        and isinstance(f.get("data"), dict)
        and str(f["data"].get("type", "")).startswith("soothe.card.")
    ]
    assert card_frames
    assert any(f["data"]["type"] == CARD_CREATED for f in card_frames)
    assert any(f["data"]["type"] == CARD_UPDATED for f in card_frames)

    ledger = await manager.ensure_for_loop("loop_append")
    texts = [c.content for c in ledger.snapshot() if c.type.value == "assistant"]
    assert texts and texts[-1] == "hello world"


if __name__ == "__main__":  # pragma: no cover - convenience
    sys.exit(pytest.main([__file__, "-v"]))
