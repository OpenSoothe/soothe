"""Tests for Context Engine persistence backend selection in StrangeLoop."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.loop.engine.strange_loop import StrangeLoop


def _make_strange_loop(*, backend: str) -> StrangeLoop:
    config = MagicMock()
    config.agent.loop.working_memory.enabled = False
    config.agent.loop.goal_context = MagicMock()
    config.agent.loop.context_engine = MagicMock()
    config.agent.loop.context_engine.to_projection_config.return_value = MagicMock()
    config.persistence.default_backend = backend
    config.persistence.postgres_base_dsn = "postgresql://postgres:postgres@127.0.0.1:6432"
    config.persistence.postgres_databases = {"checkpoints": "soothe_checkpoints"}
    config.persistence.soothe_postgres_dsn = None
    config.home = "/tmp/soothe-test"
    return StrangeLoop(core_agent=MagicMock(), loop_planner=MagicMock(), config=config)


@pytest.mark.asyncio
async def test_postgresql_backend_selects_pgsql_persistence() -> None:
    """PostgreSQL backend must not fall through to the unknown-backend error."""
    pytest.importorskip("asyncpg")
    sl = _make_strange_loop(backend="postgresql")

    with (
        patch(
            "soothe.foundation.context.persistence.pgsql_backend.PgsqlContextPersistence"
        ) as pgsql_cls,
        patch(
            "soothe.foundation.context.persistence.sqlite_backend.SqliteContextPersistence"
        ) as sqlite_cls,
        patch("soothe.foundation.context.engine.ContextEngine") as ce_cls,
        patch("soothe.foundation.context.planning.StepPlanManagerAdapter"),
        patch("soothe.foundation.loop.engine.strange_loop.StrangeLoopStateManager") as sm_cls,
        patch("soothe.foundation.loop.engine.strange_loop.CheckpointAnchorManager") as am_cls,
        patch("soothe.foundation.loop.engine.strange_loop.LoopRuntimeContext"),
        patch("soothe.foundation.loop.engine.strange_loop.asyncio.Queue"),
        patch.object(sl, "plan_phase"),
        patch(
            "soothe.foundation.workspace.tool_path_resolution.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        ce_instance = MagicMock()
        ce_instance.load = AsyncMock(return_value=True)
        ce_instance._semantic = MagicMock()
        ce_instance.get_all_goals = lambda: []
        ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
        ce_instance.activate_goal = AsyncMock()
        ce_instance.planning.step = MagicMock()
        ce_cls.return_value = ce_instance

        sm = MagicMock()
        sm.loop_id = "L1"
        sm.load = AsyncMock(return_value=None)
        sm.initialize = AsyncMock(
            return_value=MagicMock(status="idle", goal_history=[], thread_ids=[])
        )
        sm.start_new_goal = MagicMock(return_value=MagicMock(goal_id="g1", iteration=0))
        sm.save = AsyncMock()
        sm.close = AsyncMock()
        sm_cls.return_value = sm
        am_cls.return_value = MagicMock(close=AsyncMock())

        gen = sl.run_with_progress(
            goal="test goal",
            thread_id="t1",
            workspace="/tmp/ws",
            max_iterations=1,
            loop_id="L1",
        )

        async def _step() -> Any:
            async for _ in gen:
                break

        try:
            await asyncio.wait_for(_step(), timeout=2.0)
        except (TimeoutError, StopAsyncIteration, asyncio.CancelledError, TypeError):
            pass

    pgsql_cls.assert_called_once()
    sqlite_cls.assert_not_called()
