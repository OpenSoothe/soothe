"""Tests for non-blocking quiz persistence after response yield."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.runner._runner_phases import PhasesMixin


class _QuizRunner(PhasesMixin):
    def __init__(self, *, config: MagicMock | None = None, loop_id: str = "") -> None:
        self._config = config or MagicMock()
        self._client_loop_id_for_stream = loop_id
        self._materialize_core_agent = AsyncMock(return_value=MagicMock())


@pytest.mark.asyncio
async def test_run_quiz_yields_before_persistence_completes() -> None:
    """Quiz response must reach the client before ledger/checkpointer save."""
    runner = _QuizRunner()
    classification = MagicMock()
    classification.quiz_response = "Hi there!"

    save_started = asyncio.Event()
    save_release = asyncio.Event()

    async def _slow_save(*_args: object, **_kwargs: object) -> None:
        save_started.set()
        await save_release.wait()

    with patch.object(runner, "_save_quiz_to_state", side_effect=_slow_save):
        gen = runner._run_quiz("hello", "thread-1", classification)
        chunk = await anext(gen)
        assert chunk[1] == "messages"
        msg = chunk[2][0]
        assert getattr(msg, "content", "") == "Hi there!"
        assert getattr(msg, "phase", "") == "quiz"
        assert not save_started.is_set()

        with pytest.raises(StopAsyncIteration):
            await anext(gen)

        await asyncio.wait_for(save_started.wait(), timeout=1.0)
        assert not save_release.is_set()
        save_release.set()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_schedule_quiz_persistence_runs_in_background() -> None:
    """Background task eventually calls _save_quiz_to_state."""
    runner = _QuizRunner()
    done = asyncio.Event()

    async def _save(*_args: object, **_kwargs: object) -> None:
        done.set()

    with patch.object(runner, "_save_quiz_to_state", side_effect=_save):
        runner._schedule_quiz_persistence("q", "a", "thread-1")
        await asyncio.wait_for(done.wait(), timeout=1.0)
