"""Tests for trivial exchange persistence to the loop ledger."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.runner._runner_phases import PhasesMixin


class _TrivialRunner(PhasesMixin):
    def __init__(self, *, config: MagicMock, loop_id: str) -> None:
        self._config = config
        self._client_loop_id_for_stream = loop_id
        self._materialize_core_agent = AsyncMock(return_value=MagicMock())
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


@pytest.mark.asyncio
async def test_save_trivial_to_state_records_human_ai_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "context_engine.db"
    loop_id = "loop-trivial-1"
    thread_id = "thread-trivial-1"

    config = MagicMock()
    config.agent.loop.context_engine.to_projection_config.return_value = {}
    config.home = str(tmp_path)

    runner = _TrivialRunner(config=config, loop_id=loop_id)

    with patch(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        return_value=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    ):
        await runner._save_trivial_to_state("who are you?", "I am Soothe.", thread_id)

    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id=loop_id, db_path=db_path),
    )
    await ce.load()
    messages = ce.ledger.get_messages()
    assert len(messages) == 2
    assert messages[0].content == "who are you?"
    assert messages[1].content == "I am Soothe."

    entries = list(ce.ledger.entries())
    assert entries[0][1] == "trivial"
    assert entries[1][1] == "trivial"


@pytest.mark.asyncio
async def test_save_trivial_to_state_appends_to_prior_entries(tmp_path: Path) -> None:
    db_path = tmp_path / "context_engine.db"
    loop_id = "loop-trivial-2"
    thread_id = "thread-trivial-2"

    persistence = SqliteContextPersistence(loop_id=loop_id, db_path=db_path)
    ce = ContextEngine(persistence=persistence)
    from soothe.foundation.sloop.utils.messages import _record_ledger_message

    _record_ledger_message(
        ce,
        LoopHumanMessage(content="prior question", thread_id=thread_id, phase="execute_step"),
        "execute_step",
    )
    _record_ledger_message(
        ce,
        LoopAIMessage(content="prior answer", thread_id=thread_id, phase="execute_step"),
        "execute_step",
    )
    await ce.save()

    config = MagicMock()
    config.agent.loop.context_engine.to_projection_config.return_value = {}
    config.home = str(tmp_path)
    runner = _TrivialRunner(config=config, loop_id=loop_id)

    with patch(
        "soothe.foundation.context.persistence.factory.resolve_context_engine_persistence",
        return_value=persistence,
    ):
        await runner._save_trivial_to_state("hello", "Hi there!", thread_id)

    await ce.load()
    messages = ce.ledger.get_messages()
    assert len(messages) == 4
    assert messages[-2].content == "hello"
    assert messages[-1].content == "Hi there!"
