"""StrangeLoop interactive path must materialize CoreAgent before the graph.

Without a durable LangGraph checkpointer, ``await_user`` interrupts (planner
review) end the turn non-durably and Approve / ``Command(resume=...)`` is a no-op.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.runner._runner_strange_loop import StrangeLoopMixin


class _BareStrangeLoopMixin(StrangeLoopMixin):
    """Minimal mixin host for ``_run_strange_loop`` unit tests."""

    def __init__(self) -> None:
        self._agent = MagicMock()
        self._planner = MagicMock()
        self._config = MagicMock()
        self._current_thread_id = "thread-1"
        self._client_loop_id_for_stream = "loop-1"
        self._intent_classifier = None
        self._materialize_core_agent = AsyncMock(return_value=self._agent)
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


class _FakeStrangeLoop:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run_with_progress(self, **_kwargs: Any):
        # Empty async generator — graph body is not under test here.
        if False:  # pragma: no cover
            yield None


@pytest.mark.asyncio
async def test_run_strange_loop_materializes_core_agent_before_graph() -> None:
    mixin = _BareStrangeLoopMixin()
    heartbeat = MagicMock()
    heartbeat.stop = AsyncMock()

    with (
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoop",
            _FakeStrangeLoop,
        ),
        patch(
            "soothe.sloop.clarification.build_clarification_policy_for_runner",
            return_value=MagicMock(),
        ),
        patch(
            "soothe.runner._runner_strange_loop._start_loop_heartbeat",
            return_value=heartbeat,
        ),
    ):
        chunks = [c async for c in mixin._run_strange_loop("do the thing", thread_id="t1")]

    assert chunks  # StrangeLoopStartedEvent
    mixin._materialize_core_agent.assert_awaited_once()
    heartbeat.stop.assert_awaited_once()
