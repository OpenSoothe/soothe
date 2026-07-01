"""Unit tests for worker CoreAgent warmup helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from soothe_daemon.runner._worker_runner import warmup_worker_runner_on_loop


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
    "soothe_daemon.runner._worker_runner._materialize_runner_core_agent",
    new_callable=AsyncMock,
)
@patch("soothe_daemon.runner._worker_runner.acquire_worker_runner")
def test_warmup_worker_runner_materializes_core_agent(
    mock_acquire: MagicMock,
    mock_materialize: AsyncMock,
) -> None:
    """Warmup compiles LazyCoreAgent on the worker event loop."""
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
    mock_materialize.assert_awaited_once_with(
        runner,
        config=config,
        warmup_core_agent=True,
    )


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
