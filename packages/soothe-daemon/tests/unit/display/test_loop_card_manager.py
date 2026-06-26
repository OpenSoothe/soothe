"""Tests for the per-loop card manager (RFC-413).

The manager wires the SDK binder against the runner's checkpoint + activity
log to derive cards lazily. Tests use mocked runners + canned messages so we
don't need a live daemon.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_daemon.display.loop_card_manager import (
    CARD_CREATED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    LoopCardManager,
)


@pytest.fixture
def loops_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SOOTHE_HOME so PersistenceDirectoryManager writes into tmp."""
    soothe_home = tmp_path / "soothe_home"
    soothe_home.mkdir()
    # PersistenceDirectoryManager reads soothe.config.SOOTHE_HOME at call time.
    import soothe.config

    monkeypatch.setattr(soothe.config, "SOOTHE_HOME", str(soothe_home))
    # Cached module instances in directory_manager hold no state; nothing else
    # to patch.
    return soothe_home / "data" / "loops"


def _make_runner(
    checkpoint_messages: list = None,
    activity_log: list = None,
) -> SimpleNamespace:
    """Build a runner shim that returns the canned values."""
    runner = MagicMock()
    runner.get_thread_state_values = AsyncMock(return_value={"messages": checkpoint_messages or []})
    runner.get_persisted_thread_messages = AsyncMock(return_value=activity_log or [])
    return runner


def _patch_bind_thread(monkeypatch: pytest.MonkeyPatch, thread_id: str = "thread_x") -> None:
    """Make bind_execution_thread_for_loop return a deterministic id."""
    import soothe_daemon.runtime.loop_dispatcher as dispatcher

    async def _fake(_daemon, _loop_id):
        return thread_id

    monkeypatch.setattr(dispatcher, "bind_execution_thread_for_loop", _fake)


def _patch_langgraph_checkpoint(monkeypatch: pytest.MonkeyPatch, *, exists: bool) -> None:
    """Control LangGraph checkpoint probe used by the empty-loop fast path."""
    import soothe_daemon.display.loop_card_manager as lcm

    async def _fake(_thread_id: str) -> bool:
        return exists

    monkeypatch.setattr(lcm, "langgraph_checkpoint_exists", _fake)


@pytest.mark.asyncio
async def test_ensure_for_loop_backfills_from_checkpoint(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
    messages = [
        HumanMessage(content="hello"),
        AIMessage(content="hi there"),
    ]
    runner = _make_runner(checkpoint_messages=messages)
    daemon = SimpleNamespace(_runner=runner)

    manager = LoopCardManager(daemon)
    ledger = await manager.ensure_for_loop("loop_a")
    snapshot = ledger.snapshot()
    assert [c.content for c in snapshot] == ["hello", "hi there"]
    assert (loops_root / "loop_a" / "cards.jsonl").exists()


@pytest.mark.asyncio
async def test_ensure_for_loop_uses_activity_log_when_no_checkpoint(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
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
    runner = _make_runner(checkpoint_messages=[], activity_log=activity)
    daemon = SimpleNamespace(_runner=runner)

    manager = LoopCardManager(daemon)
    ledger = await manager.ensure_for_loop("loop_b")
    snapshot = ledger.snapshot()
    assert [c.content for c in snapshot] == ["from log", "log reply"]


@pytest.mark.asyncio
async def test_ensure_for_loop_returns_empty_when_no_data(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    runner = _make_runner(checkpoint_messages=[], activity_log=[])
    daemon = SimpleNamespace(_runner=runner)

    manager = LoopCardManager(daemon)
    ledger = await manager.ensure_for_loop("loop_empty")
    assert ledger.card_count() == 0
    runner.get_thread_state_values.assert_not_called()
    # cards.jsonl is still created (just contains the header).
    assert (loops_root / "loop_empty" / "cards.jsonl").exists()


@pytest.mark.asyncio
async def test_is_display_empty_skips_core_agent_checkpoint_read(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    runner = _make_runner(checkpoint_messages=[], activity_log=[])
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)

    assert await manager.is_display_empty("loop_fast") is True
    runner.get_thread_state_values.assert_not_called()


@pytest.mark.asyncio
async def test_replay_to_client_empty_loop_skips_checkpoint_read(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    runner = _make_runner(checkpoint_messages=[], activity_log=[])
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)

    sent: list[dict] = []

    async def collect(frame: dict) -> None:
        sent.append(frame)

    total = await manager.replay_to_client("loop_fast_replay", collect)
    assert total == 0
    runner.get_thread_state_values.assert_not_called()
    assert sent[0]["type"] == CARD_REPLAY_BEGIN
    assert sent[-1]["type"] == CARD_REPLAY_END
    assert sent[0]["total_cards"] == 0


@pytest.mark.asyncio
async def test_refresh_empty_loop_is_noop(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    runner = _make_runner(checkpoint_messages=[], activity_log=[])
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)

    ledger = await manager.refresh("loop_refresh_empty")
    assert ledger.card_count() == 0
    runner.get_thread_state_values.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_re_derives_after_messages_added(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
    runner = _make_runner(checkpoint_messages=[HumanMessage(content="round1")])
    daemon = SimpleNamespace(_runner=runner)

    manager = LoopCardManager(daemon)
    ledger = await manager.ensure_for_loop("loop_c")
    assert [c.content for c in ledger.snapshot()] == ["round1"]

    # Simulate more turn(s): runner now reports more messages.
    runner.get_thread_state_values = AsyncMock(
        return_value={
            "messages": [
                HumanMessage(content="round1"),
                AIMessage(content="reply1"),
                HumanMessage(content="round2"),
            ]
        }
    )
    await manager.refresh("loop_c")
    contents = [c.content for c in ledger.snapshot()]
    assert contents == ["round1", "reply1", "round2"]


@pytest.mark.asyncio
async def test_replay_to_client_emits_begin_created_end(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
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
    runner = _make_runner(checkpoint_messages=messages)
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)
    await manager.ensure_for_loop("loop_d")

    sent: list[dict] = []

    async def collect(frame):
        sent.append(frame)

    total = await manager.replay_to_client("loop_d", collect)

    # One begin, N created, one end.
    types = [f["type"] for f in sent]
    assert types[0] == CARD_REPLAY_BEGIN
    assert types[-1] == CARD_REPLAY_END
    middle = [t for t in types[1:-1]]
    assert all(t == CARD_CREATED for t in middle)
    assert len(middle) == total

    # Begin frame metadata
    assert sent[0]["total_cards"] == total
    # End frame metadata
    assert sent[-1]["card_count"] == total

    # Each created frame carries data + card_id + kind.
    for frame in sent[1:-1]:
        assert frame["loop_id"] == "loop_d"
        assert frame["card_id"]
        assert frame["kind"]
        assert isinstance(frame["data"], dict)
        assert "type" in frame["data"]


@pytest.mark.asyncio
async def test_replay_to_client_refreshes_before_replay(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
    runner = _make_runner(checkpoint_messages=[HumanMessage(content="turn1")])
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)
    await manager.ensure_for_loop("loop_refresh")

    # Simulate new persisted state after the initial derivation.
    runner.get_thread_state_values = AsyncMock(
        return_value={
            "messages": [
                HumanMessage(content="turn1"),
                AIMessage(content="final goal completion response"),
            ]
        }
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
async def test_stop_for_loop_releases_in_memory_state(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    _patch_langgraph_checkpoint(monkeypatch, exists=True)
    runner = _make_runner(checkpoint_messages=[HumanMessage(content="x")])
    daemon = SimpleNamespace(_runner=runner)
    manager = LoopCardManager(daemon)
    await manager.ensure_for_loop("loop_e")
    assert "loop_e" in manager._ledgers  # noqa: SLF001

    await manager.stop_for_loop("loop_e")
    assert "loop_e" not in manager._ledgers  # noqa: SLF001

    # File still exists on disk; only in-memory state was released.
    assert (loops_root / "loop_e" / "cards.jsonl").exists()


@pytest.mark.asyncio
async def test_ensure_for_loop_handles_runner_unavailable(
    loops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bind_thread(monkeypatch)
    daemon = SimpleNamespace(_runner=None)
    manager = LoopCardManager(daemon)
    ledger = await manager.ensure_for_loop("loop_no_runner")
    # No runner → no cards, but ledger file is created.
    assert ledger.card_count() == 0
    assert (loops_root / "loop_no_runner" / "cards.jsonl").exists()


if __name__ == "__main__":  # pragma: no cover - convenience
    sys.exit(pytest.main([__file__, "-v"]))
