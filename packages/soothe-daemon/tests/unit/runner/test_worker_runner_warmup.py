"""Unit tests for worker CoreAgent warmup helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_daemon.runner._worker_runner import (
    _warmup_worker_core_agent,
    warmup_worker_runner_on_loop,
)


class _FakeLazyCoreAgent:
    """Stand-in for LazyCoreAgent in isinstance checks."""

    is_materialized: bool = False


@patch("soothe_daemon.runner._worker_runner.acquire_worker_runner")
def test_warmup_worker_runner_skips_core_agent_when_disabled(
    mock_acquire: MagicMock,
) -> None:
    """CoreAgent materialization is optional during worker warmup."""
    runner = MagicMock()
    mock_acquire.return_value = (runner, runner)
    config = MagicMock()
    config.agent.runtime.lazy_core_agent = True

    loop = asyncio.new_event_loop()
    try:
        result = warmup_worker_runner_on_loop(
            loop,
            config=config,
            reuse_runner=True,
            warmup_runner=True,
            warmup_core_agent=False,
            worker_id="thread-worker-0",
        )
    finally:
        loop.close()

    assert result is runner
    runner._materialize_core_agent.assert_not_called()


@patch(
    "soothe_daemon.runner._worker_runner._warmup_worker_core_agent",
    new_callable=AsyncMock,
)
@patch("soothe_daemon.runner._worker_runner.acquire_worker_runner")
def test_warmup_worker_runner_materializes_core_agent(
    mock_acquire: MagicMock,
    mock_warmup: AsyncMock,
) -> None:
    """Warmup compiles CoreAgent graphs on the worker event loop."""
    runner = MagicMock()
    mock_acquire.return_value = (runner, runner)
    config = MagicMock()
    config.agent.runtime.lazy_core_agent = True

    loop = asyncio.new_event_loop()
    try:
        result = warmup_worker_runner_on_loop(
            loop,
            config=config,
            reuse_runner=True,
            warmup_runner=True,
            warmup_core_agent=True,
            worker_id="thread-worker-0",
        )
    finally:
        loop.close()

    assert result is runner
    mock_warmup.assert_awaited_once_with(
        runner,
        config=config,
        warmup_core_agent=True,
    )


@pytest.mark.asyncio
async def test_warmup_worker_core_agent_touches_execution_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warmup compiles the ephemeral execute twin after primary materialize."""
    execute_graph = MagicMock(name="execute_graph")
    materialized = MagicMock()
    materialized.execution_graph = execute_graph

    lazy_agent = _FakeLazyCoreAgent()
    lazy_agent.is_materialized = False

    runner = MagicMock()
    runner._core_agent = lazy_agent
    runner._materialize_core_agent = AsyncMock(return_value=materialized)
    runner._materialized_core_agent.return_value = materialized

    config = MagicMock()
    config.agent.runtime.lazy_core_agent = True

    monkeypatch.setattr(
        "soothe.foundation.coreagent.lazy.LazyCoreAgent",
        _FakeLazyCoreAgent,
    )
    monkeypatch.setattr(
        "soothe_nano.agent.core_agent.ephemeral_execute_stream_enabled",
        lambda: True,
    )

    await _warmup_worker_core_agent(
        runner,
        config=config,
        warmup_core_agent=True,
    )

    runner._materialize_core_agent.assert_awaited_once()
    runner._materialized_core_agent.assert_called_once()
    assert materialized.execution_graph is execute_graph


@pytest.mark.asyncio
async def test_warmup_worker_core_agent_skips_execution_graph_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute twin warmup is skipped when ephemeral execute streaming is off."""
    lazy_agent = _FakeLazyCoreAgent()
    lazy_agent.is_materialized = True

    runner = MagicMock()
    runner._core_agent = lazy_agent

    config = MagicMock()
    config.agent.runtime.lazy_core_agent = True

    monkeypatch.setattr(
        "soothe.foundation.coreagent.lazy.LazyCoreAgent",
        _FakeLazyCoreAgent,
    )
    monkeypatch.setattr(
        "soothe_nano.agent.core_agent.ephemeral_execute_stream_enabled",
        lambda: False,
    )

    await _warmup_worker_core_agent(
        runner,
        config=config,
        warmup_core_agent=True,
    )

    runner._materialize_core_agent.assert_not_called()
    runner._materialized_core_agent.assert_not_called()


def test_warmup_worker_runner_returns_none_when_reuse_disabled() -> None:
    """No cached runner is created when reuse is disabled."""
    loop = asyncio.new_event_loop()
    try:
        result = warmup_worker_runner_on_loop(
            loop,
            config=MagicMock(),
            reuse_runner=False,
            warmup_runner=True,
            warmup_core_agent=True,
        )
    finally:
        loop.close()

    assert result is None
