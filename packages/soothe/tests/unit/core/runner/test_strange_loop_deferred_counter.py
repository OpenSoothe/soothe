"""Tests for non-blocking loop message counter bump after goal completion."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from soothe.runner._runner_strange_loop import _schedule_increment_loop_ai_message_count


@pytest.mark.asyncio
async def test_schedule_increment_loop_ai_message_count_runs_in_background() -> None:
    done = asyncio.Event()

    class _Pm:
        async def increment_loop_message_count(self, *_args: object, **_kwargs: object) -> None:
            done.set()

        async def close(self) -> None:
            return None

    with patch(
        "soothe.foundation.sloop.state.persistence.StrangeLoopCheckpointPersistenceManager",
        return_value=_Pm(),
    ):
        _schedule_increment_loop_ai_message_count(MagicMock(), "loop-1")
        await asyncio.wait_for(done.wait(), timeout=1.0)
