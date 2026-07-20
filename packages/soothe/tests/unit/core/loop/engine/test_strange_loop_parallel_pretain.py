"""Tests for RFC-630 Phase C: parallelized pre-graph IO in ``StrangeLoop``.

Verifies that the semantic file reads (``load_project_instructions``,
``load_agent_instructions``, ``load_memory``) run via ``asyncio.to_thread``
and concurrently with ``ce.load()``, rather than sequentially on the event
loop. Uses ``asyncio.Event`` latches to assert concurrency.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.engine.strange_loop import StrangeLoop


def _make_strange_loop() -> StrangeLoop:
    """Build a StrangeLoop with mocked planner/core_agent/config."""
    config = MagicMock()
    config.agent.loop.working_memory.enabled = False
    config.agent.loop.goal_context = MagicMock()
    config.agent.loop.context_engine = MagicMock()
    config.persistence.default_backend = "sqlite"
    config.persistence.postgres_base_dsn = None
    config.persistence.soothe_postgres_dsn = None
    config.home = "/tmp/soothe-test"
    return StrangeLoop(core_agent=MagicMock(), loop_planner=MagicMock(), config=config)


@pytest.mark.asyncio
async def test_semantic_reads_run_concurrently_with_ce_load() -> None:
    """RFC-630 Phase C: ce.load() and the 3 file reads overlap, not sequential.

    Each mocked call blocks on its own Event until released; if they ran
    sequentially the test would deadlock (the first call would never release
    the second). Gathering them all at once lets each proceed.
    """
    sl = _make_strange_loop()

    # Latches: each call waits for permission to complete.
    load_started = asyncio.Event()
    load_release = asyncio.Event()
    proj_started = asyncio.Event()
    proj_release = asyncio.Event()
    agent_started = asyncio.Event()
    agent_release = asyncio.Event()
    mem_started = asyncio.Event()
    mem_release = asyncio.Event()

    async def fake_ce_load() -> bool:
        load_started.set()
        await load_release.wait()
        return True

    def fake_proj() -> None:
        proj_started.set()
        # to_thread runs this in a worker thread; spin-wait on the release.
        import time

        while not proj_release.is_set():
            time.sleep(0.001)

    def fake_agent() -> None:
        agent_started.set()
        import time

        while not agent_release.is_set():
            time.sleep(0.001)

    def fake_mem() -> None:
        mem_started.set()
        import time

        while not mem_release.is_set():
            time.sleep(0.001)

    # Mock the CE instance and its semantic sub-engine.
    semantic = MagicMock()
    semantic.load_project_instructions = fake_proj
    semantic.load_agent_instructions = fake_agent
    semantic.load_memory = fake_mem
    semantic.workspace = None

    ce_instance = MagicMock()
    ce_instance.load = fake_ce_load
    ce_instance._semantic = semantic
    ce_instance.get_all_goals = lambda: []
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()

    # Stub everything else in run_with_progress so we isolate the gather block.
    with (
        patch.object(sl, "_ce", None),
        patch("soothe.foundation.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.foundation.context.persistence.sqlite_backend.SqliteContextPersistence"),
        patch(
            "soothe.foundation.sloop.state.persistence.runtime_paths.resolve_context_engine_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch("soothe.foundation.context.planning.StepPlanManagerAdapter"),
        patch("soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager") as sm_cls,
        patch("soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager") as am_cls,
        patch("soothe.foundation.sloop.engine.strange_loop.LoopRuntimeContext"),
        patch("soothe.foundation.sloop.engine.strange_loop.asyncio.Queue"),
        patch.object(sl, "plan_phase"),
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        sm = MagicMock()
        sm.loop_id = "L1"
        sm.load = AsyncMock(return_value=None)  # fresh checkpoint
        sm.initialize = AsyncMock(
            return_value=MagicMock(status="idle", goal_history=[], thread_ids=[])
        )
        sm.start_new_goal = MagicMock(return_value=MagicMock(goal_id="g1", iteration=0))
        sm.save = AsyncMock()
        sm.close = AsyncMock()  # Fix: must be AsyncMock for cleanup path
        sm_cls.return_value = sm

        am = MagicMock()
        am.close = AsyncMock()  # Fix: must be AsyncMock for cleanup path
        am_cls.create = AsyncMock(return_value=am)

        # Drive run_with_progress one step: it yields events; we just need the
        # gather block to run. Consume the generator briefly.
        gen = sl.run_with_progress(
            goal="test goal",
            thread_id="t1",
            workspace="/tmp/ws",
            max_iterations=1,
            loop_id="L1",
        )

        # Start the generator; the gather block runs before the first yield.
        # Use a timeout so the test can't truly deadlock.
        async def _step() -> Any:
            async for _ in gen:  # noqa: F841
                break

        try:
            await asyncio.wait_for(_step(), timeout=2.0)
        except (TimeoutError, StopAsyncIteration, asyncio.CancelledError):
            pass

        # All four calls should have started (concurrency proof): if they were
        # sequential, the first would block forever waiting for its release
        # while the others never started.
        assert load_started.is_set(), "ce.load() did not start"
        assert proj_started.is_set(), "load_project_instructions did not start"
        assert agent_started.is_set(), "load_agent_instructions did not start"
        assert mem_started.is_set(), "load_memory did not start"

        # Release all so background tasks can finish (avoid dangling threads).
        load_release.set()
        proj_release.set()
        agent_release.set()
        mem_release.set()
