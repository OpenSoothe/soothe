"""Tests for chitchat intake fast-path (piggybacked response)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.runner._runner_phases import PhasesMixin


class _ChitchatRunner(PhasesMixin):
    def __init__(self, *, config: MagicMock, loop_id: str) -> None:
        self._config = config
        self._client_loop_id_for_stream = loop_id
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


@pytest.mark.asyncio
async def test_save_chitchat_to_ledger_records_human_ai_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "context_engine.db"
    loop_id = "loop-chitchat-1"
    main_thread_id = loop_id

    config = MagicMock()
    config.agent.loop.context_engine.to_projection_config.return_value = {}
    config.home = str(tmp_path)

    runner = _ChitchatRunner(config=config, loop_id=loop_id)

    with patch(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        return_value=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    ):
        await runner._save_chitchat_to_ledger(
            "how are u",
            "I'm doing well, thanks for asking!",
            main_thread_id,
            context_engine=None,
        )

    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    )
    await ce.load()
    messages = ce.ledger.get_messages()
    assert len(messages) == 2
    assert messages[0].content == "how are u"
    assert messages[1].content == "I'm doing well, thanks for asking!"

    entries = list(ce.ledger.entries())
    assert entries[0][1] == "chitchat"
    assert entries[1][1] == "chitchat"


@pytest.mark.asyncio
async def test_run_chitchat_finalizes_identity_query() -> None:
    config = MagicMock()
    config.agent.name = "Soothe"
    runner = _ChitchatRunner(config=config, loop_id="loop-chitchat-identity")
    runner._save_chitchat_to_state = AsyncMock()

    chunks = [
        c
        async for c in runner._run_chitchat(
            "what is your name",
            "thread-1",
            chitchat_response="I'm Claude, an AI assistant made by Anthropic.",
            loop_id="loop-chitchat-identity",
            defer_persistence=True,
        )
    ]

    assert len(chunks) == 1
    content = chunks[0][2][0].content
    assert "Soothe" in content
    assert "Dr. Xiaming Chen" in content
    assert "Claude" not in content


@pytest.mark.asyncio
async def test_run_chitchat_emits_single_response_chunk() -> None:
    runner = _ChitchatRunner(config=MagicMock(), loop_id="loop-chitchat-2")
    runner._save_chitchat_to_state = AsyncMock()

    chunks = [
        c
        async for c in runner._run_chitchat(
            "hello",
            "thread-1",
            chitchat_response="Hello! How can I help you today?",
            loop_id="loop-chitchat-2",
        )
    ]

    assert len(chunks) == 1
    _namespace, mode, data = chunks[0]
    assert mode == "messages"
    msg = data[0]
    assert getattr(msg, "content", "") == "Hello! How can I help you today?"
    assert getattr(msg, "phase", "") == "chitchat"
    runner._save_chitchat_to_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_chitchat_awaits_persistence_before_finishing() -> None:
    runner = _ChitchatRunner(config=MagicMock(), loop_id="loop-chitchat-3")

    save_started = asyncio.Event()
    save_release = asyncio.Event()

    async def _slow_save(*_args: object, **_kwargs: object) -> None:
        save_started.set()
        await save_release.wait()

    with patch.object(runner, "_save_chitchat_to_state", side_effect=_slow_save):
        gen = runner._run_chitchat(
            "hi",
            "thread-1",
            chitchat_response="Hi there!",
            loop_id="loop-chitchat-3",
        )
        chunk = await anext(gen)
        assert chunk[2][0].content == "Hi there!"
        assert not save_started.is_set()

        drain_task = asyncio.create_task(anext(gen))
        await asyncio.wait_for(save_started.wait(), timeout=1.0)

        save_release.set()
        with pytest.raises(StopAsyncIteration):
            await drain_task


@pytest.mark.asyncio
async def test_run_chitchat_defer_persistence_skips_save_in_generator() -> None:
    runner = _ChitchatRunner(config=MagicMock(), loop_id="loop-chitchat-4")
    runner._save_chitchat_to_state = AsyncMock()

    chunks = [
        c
        async for c in runner._run_chitchat(
            "hello",
            "thread-1",
            chitchat_response="Hey!",
            loop_id="loop-chitchat-4",
            defer_persistence=True,
        )
    ]

    assert len(chunks) == 1
    runner._save_chitchat_to_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_chitchat_skips_running_checkpoint() -> None:
    from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry

    config = MagicMock()
    runner = _ChitchatRunner(config=config, loop_id="loop-running")

    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    goal = GoalIndexEntry(
        goal_id="goal-0",
        status="running",
        thread_id="loop-running",
        started_at=now,
        completed_at=None,
        duration_ms=0,
        tokens_used=0,
    )
    checkpoint = MagicMock()
    checkpoint.status = "running"
    checkpoint.current_goal_index = 0
    checkpoint.goal_history = [goal]

    mock_sm = MagicMock()
    mock_sm.load = AsyncMock(return_value=checkpoint)
    mock_sm.finalize_goal = AsyncMock()
    mock_sm.close = AsyncMock()
    runner.get_sloop_shared_pool = AsyncMock(return_value=None)

    with patch(
        "soothe.foundation.sloop.state.sloop_manager.StrangeLoopStateManager",
        return_value=mock_sm,
    ):
        await runner._finalize_chitchat_loop("loop-running", response="Hi!")

    mock_sm.finalize_goal.assert_not_awaited()
