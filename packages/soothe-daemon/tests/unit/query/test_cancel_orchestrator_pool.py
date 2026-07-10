"""Tests for AsyncCancelOrchestrator execution-pool wiring."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.query.engine import AsyncCancelOrchestrator, QueryEngine


class _FakeExecutionPool:
    def __init__(self) -> None:
        self._loop_workers = {"loop-a": "thread-worker-1"}
        self._idle: dict[str, bool] = {"thread-worker-1": False}
        self.force_cancel_worker = AsyncMock()

    def get_worker_id_for_loop(self, loop_id: str) -> str | None:
        return self._loop_workers.get(loop_id)

    def is_worker_idle(self, worker_id: str) -> bool:
        return self._idle.get(worker_id, True)


class _FakeRunnerFactory:
    def __init__(self, pool: _FakeExecutionPool) -> None:
        self._pool = pool

    async def get_shared_execution_pool(self) -> _FakeExecutionPool:
        return self._pool


class _FakeThreadRegistry:
    def get_thread_loop(self, _thread_id: str) -> str | None:
        return None


@pytest.mark.asyncio
async def test_cancel_orchestrator_resolves_worker_from_execution_pool() -> None:
    pool = _FakeExecutionPool()
    daemon = SimpleNamespace(
        _runner_factory=_FakeRunnerFactory(pool),
        _daemon_config=SootheDaemonConfig(),
    )
    query_engine = MagicMock(spec=QueryEngine)
    query_engine._active_runners = {}
    query_engine.collect_active_tasks_for_loop = MagicMock(return_value=[])

    orchestrator = AsyncCancelOrchestrator(daemon, query_engine)

    worker_id = await orchestrator._get_worker_id_for_loop("loop-a")
    assert worker_id == "thread-worker-1"
    assert await orchestrator._is_worker_idle(worker_id) is False

    pool._idle["thread-worker-1"] = True
    assert await orchestrator._is_worker_idle(worker_id) is True


@pytest.mark.asyncio
async def test_cancel_orchestrator_unknown_worker_is_not_idle() -> None:
    daemon = SimpleNamespace(
        _runner_factory=_FakeRunnerFactory(_FakeExecutionPool()),
        _daemon_config=SootheDaemonConfig(),
    )
    query_engine = MagicMock(spec=QueryEngine)
    orchestrator = AsyncCancelOrchestrator(daemon, query_engine)

    assert await orchestrator._get_worker_id_for_loop("missing") is None
    assert await orchestrator._is_worker_idle(None) is False


@pytest.mark.asyncio
async def test_cancel_orchestrator_force_kill_releases_query_admission() -> None:
    """Verify force kill path releases query admission so loop accepts future queries.

    Bug: after force kill, _loops_with_active_query still contained the loop_id,
    causing all subsequent queries to be rejected as LOOP_BUSY.
    """
    pool = _FakeExecutionPool()
    pool._idle["thread-worker-1"] = False  # Simulate busy worker (won't go idle)

    daemon = SimpleNamespace(
        _runner_factory=_FakeRunnerFactory(pool),
        _daemon_config=SootheDaemonConfig(
            cancel_retry_count=1,
            cancel_retry_interval_seconds=0.5,
            cancel_force_kill_timeout_seconds=5.0,
        ),
        _query_state_lock=asyncio.Lock(),
        _loops_with_active_query={"loop-a"},
        _active_threads={},
        _current_query_task=None,
        _runner=None,
        _thread_registry=_FakeThreadRegistry(),
    )

    query_engine = QueryEngine(daemon)
    orchestrator = AsyncCancelOrchestrator(daemon, query_engine)

    await orchestrator._cancel_with_retry_and_force("loop-a")

    pool.force_cancel_worker.assert_called_once()
    assert "loop-a" not in daemon._loops_with_active_query
