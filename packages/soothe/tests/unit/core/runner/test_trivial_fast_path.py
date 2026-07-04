"""Tests for trivial intake fast-path (CoreAgent on loop main thread)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.runner._runner_phases import PhasesMixin


class _TrivialRunner(PhasesMixin):
    def __init__(self, *, config: MagicMock, loop_id: str) -> None:
        self._config = config
        self._client_loop_id_for_stream = loop_id
        self._materialize_core_agent = AsyncMock(return_value=MagicMock())
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


@pytest.mark.asyncio
async def test_save_trivial_to_ledger_records_human_ai_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "context_engine.db"
    loop_id = "loop-trivial-1"
    main_thread_id = loop_id

    config = MagicMock()
    config.agent.loop.context_engine.to_projection_config.return_value = {}
    config.home = str(tmp_path)

    runner = _TrivialRunner(config=config, loop_id=loop_id)

    with patch(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        return_value=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    ):
        await runner._save_trivial_to_ledger(
            "what time is it",
            "It is 15:00.",
            main_thread_id,
            context_engine=None,
        )

    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    )
    await ce.load()
    messages = ce.ledger.get_messages()
    assert len(messages) == 2
    assert messages[0].content == "what time is it"
    assert messages[1].content == "It is 15:00."

    entries = list(ce.ledger.entries())
    assert entries[0][1] == "trivial"
    assert entries[1][1] == "trivial"


@pytest.mark.asyncio
async def test_run_trivial_uses_loop_id_as_main_thread_and_persists() -> None:
    runner = _TrivialRunner(config=MagicMock(), loop_id="loop-main-1")
    runner._ensure_checkpointer_initialized = AsyncMock()
    runner._schedule_trivial_persistence = MagicMock()

    async def _fake_astream(*_args, **_kwargs):
        chunk = (
            (),
            "messages",
            (AIMessage(content="It is 3 PM."), {}),
        )
        yield chunk

    core_agent = MagicMock()
    core_agent.astream = _fake_astream
    core_agent.aget_state = AsyncMock(return_value=None)
    runner._materialized_core_agent = MagicMock(return_value=core_agent)

    with patch(
        "soothe.utils.observability.langfuse.SootheLangfuse",
    ) as mock_lf:
        mock_lf.return_value.traced_llm.return_value = {"configurable": {}}
        with patch(
            "soothe.runner._runner_strange_loop._forward_messages_chunk",
            return_value=True,
        ):
            chunks = [
                c
                async for c in runner._run_trivial(
                    "what time is it",
                    "client-thread",
                    loop_id="loop-main-1",
                )
            ]

    assert chunks
    runner._schedule_trivial_persistence.assert_called_once()
    call = runner._schedule_trivial_persistence.call_args
    assert call.args[2] == "loop-main-1"


@pytest.mark.asyncio
async def test_run_trivial_yields_before_persistence_completes() -> None:
    """Trivial response must reach the client before ledger finalize runs."""
    runner = _TrivialRunner(config=MagicMock(), loop_id="loop-trivial-1")
    runner._ensure_checkpointer_initialized = AsyncMock()

    save_started = asyncio.Event()
    save_release = asyncio.Event()

    async def _slow_save(*_args: object, **_kwargs: object) -> None:
        save_started.set()
        await save_release.wait()

    async def _fake_astream(*_args, **_kwargs):
        chunk = (
            (),
            "messages",
            (AIMessage(content="Hi there!"), {}),
        )
        yield chunk

    core_agent = MagicMock()
    core_agent.astream = _fake_astream
    core_agent.aget_state = AsyncMock(return_value=None)
    runner._materialized_core_agent = MagicMock(return_value=core_agent)

    with (
        patch("soothe.utils.observability.langfuse.SootheLangfuse") as mock_lf,
        patch(
            "soothe.runner._runner_strange_loop._forward_messages_chunk",
            return_value=True,
        ),
        patch.object(runner, "_save_trivial_to_state", side_effect=_slow_save),
    ):
        mock_lf.return_value.traced_llm.return_value = {"configurable": {}}
        gen = runner._run_trivial("hello", "thread-1", loop_id="loop-trivial-1")
        chunk = await anext(gen)
        assert chunk[1] == "messages"
        msg = chunk[2][0]
        assert getattr(msg, "content", "") == "Hi there!"
        assert getattr(msg, "phase", "") == "trivial"
        assert not save_started.is_set()

        with pytest.raises(StopAsyncIteration):
            await anext(gen)

        await asyncio.wait_for(save_started.wait(), timeout=1.0)
        save_release.set()
        await asyncio.sleep(0)
