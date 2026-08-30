"""Tests for the LLM stream semaphore (global_max_llm_calls).

The semaphore gates concurrent active LLM streams across parallel steps in one
execute wave. Steps that don't get a slot block before opening a stream,
preventing dispatch_idle_seconds false positives from LLM scheduling latency.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from soothe.config import SootheConfig
from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.engine.execute.graph_interrupt import DispatchTimeoutError
from soothe.sloop.engine.execute.step_wave_types import _StreamCollectChunk
from soothe.sloop.state.schemas import LoopState, StepAction, StepExecutionRecord


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_mock_agent() -> MagicMock:
    """Mock CoreAgent with the attributes Executor reads during step execution."""
    agent = MagicMock()
    agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
    agent.execution_aget_state = AsyncMock(return_value=MagicMock())
    agent.aget_state = AsyncMock(return_value=MagicMock())
    agent.can_read_graph_state = False
    return agent


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    """Empty async generator for mocked LLM streams."""
    if False:  # pragma: no cover
        yield


def _make_config(global_max_llm_calls: int) -> SootheConfig:
    """Build a SootheConfig with the given global_max_llm_calls."""
    cfg = SootheConfig()
    cfg.agent.loop.concurrency.global_max_llm_calls = global_max_llm_calls
    cfg.agent.loop.dispatch_idle_seconds = 0  # disable watchdog in tests
    cfg.agent.loop.execute_action_retry_max = 0  # no retries
    return cfg


class TestLLMStreamSemaphore:
    """Verify the semaphore limits concurrent active LLM streams."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_llm_streams(self) -> None:
        """At most global_max_llm_calls steps hold an active stream at once."""
        cfg = _make_config(global_max_llm_calls=2)
        executor = Executor(_make_mock_agent(), max_parallel_steps=4, config=cfg)

        current = 0
        peak = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.05)  # simulate stream duration
            current -= 1
            yield _StreamCollectChunk.finalized(
                output="done",
                main_tool_count=1,
                messages=[AIMessage(content="done")],
                delegate_final="",
                outcomes=[{"type": "generic"}],
                has_error=False,
                subgraph_tool_count=0,
            )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-sem", iteration=0, max_iterations=4)
            steps = [StepAction(id=f"s{i}", description=f"step {i}") for i in range(4)]

            async for _ in executor._execute_parallel(steps, state):
                pass

        assert peak <= 2, f"peak concurrent streams {peak} exceeded limit 2"
        assert peak >= 2, f"peak {peak} — semaphore should allow up to 2"

    @pytest.mark.asyncio
    async def test_semaphore_released_on_stream_exception(self) -> None:
        """Semaphore is released when _stream_and_collect raises."""
        cfg = _make_config(global_max_llm_calls=1)
        executor = Executor(_make_mock_agent(), max_parallel_steps=1, config=cfg)

        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("stream exploded")
            yield  # pragma: no cover

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-err", iteration=0, max_iterations=4)
            step = StepAction(id="s0", description="boom")

            results: list[Any] = []
            async for item in executor._execute_parallel([step], state):
                results.append(item)

        # Step should have failed (exception caught by _run_parallel_step)
        assert call_count == 1
        assert any(isinstance(r, StepExecutionRecord) and not r.success for r in results)

        # Semaphore must be released — a new acquire should succeed immediately.
        assert executor._llm_stream_semaphore is not None
        # _value is the internal counter: full capacity = 1.
        assert executor._llm_stream_semaphore._value == 1

    @pytest.mark.asyncio
    async def test_zero_means_unlimited(self) -> None:
        """With global_max_llm_calls=0, no semaphore gates streams."""
        cfg = _make_config(global_max_llm_calls=0)
        executor = Executor(_make_mock_agent(), max_parallel_steps=4, config=cfg)

        assert executor._llm_stream_semaphore is None

        peak = 0
        current = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.05)
            current -= 1
            yield _StreamCollectChunk.finalized(
                output="done",
                main_tool_count=1,
                messages=[AIMessage(content="done")],
                delegate_final="",
                outcomes=[{"type": "generic"}],
                has_error=False,
                subgraph_tool_count=0,
            )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-unlim", iteration=0, max_iterations=4)
            steps = [StepAction(id=f"s{i}", description=f"step {i}") for i in range(4)]

            async for _ in executor._execute_parallel(steps, state):
                pass

        # All 4 ran concurrently (no semaphore).
        assert peak == 4

    @pytest.mark.asyncio
    async def test_no_config_means_no_semaphore(self) -> None:
        """Without config, the semaphore is None (unlimited)."""
        executor = Executor(_make_mock_agent(), max_parallel_steps=4)
        assert executor._llm_stream_semaphore is None


class TestDispatchTimeoutRetry:
    """Verify DispatchTimeoutError is retried up to dispatch_retry_max times."""

    @pytest.mark.asyncio
    async def test_dispatch_timeout_retried_then_succeeds(self) -> None:
        """Step stalls twice then succeeds on third attempt."""
        cfg = _make_config(global_max_llm_calls=0)
        cfg.agent.loop.dispatch_idle_seconds = 0.01
        cfg.agent.loop.dispatch_retry_max = 3
        cfg.agent.loop.execute_action_retry_max = 0
        executor = Executor(_make_mock_agent(), max_parallel_steps=1, config=cfg)

        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise DispatchTimeoutError(0.01, step_id="s0")
            yield _StreamCollectChunk.finalized(
                output="done",
                main_tool_count=1,
                messages=[AIMessage(content="done")],
                delegate_final="",
                outcomes=[{"type": "generic"}],
                has_error=False,
                subgraph_tool_count=0,
            )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-rtry", iteration=0, max_iterations=4)
            step = StepAction(id="s0", description="retry me")

            results: list[Any] = []
            async for item in executor._execute_parallel([step], state):
                results.append(item)

        assert call_count == 3
        step_results = [r for r in results if isinstance(r, StepExecutionRecord)]
        assert len(step_results) == 1
        assert step_results[0].success

    @pytest.mark.asyncio
    async def test_dispatch_timeout_exhausts_retries_then_fails(self) -> None:
        """Step stalls on every attempt; fails after dispatch_retry_max + 1 tries."""
        cfg = _make_config(global_max_llm_calls=0)
        cfg.agent.loop.dispatch_idle_seconds = 0.01
        cfg.agent.loop.dispatch_retry_max = 2
        cfg.agent.loop.execute_action_retry_max = 0
        executor = Executor(_make_mock_agent(), max_parallel_steps=1, config=cfg)

        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            raise DispatchTimeoutError(0.01, step_id="s0")
            yield  # pragma: no cover

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-fail", iteration=0, max_iterations=4)
            step = StepAction(id="s0", description="always stall")

            results: list[Any] = []
            async for item in executor._execute_parallel([step], state):
                results.append(item)

        # 1 initial + 2 retries = 3 total attempts
        assert call_count == 3
        step_results = [r for r in results if isinstance(r, StepExecutionRecord)]
        assert len(step_results) == 1
        assert not step_results[0].success

    @pytest.mark.asyncio
    async def test_dispatch_retry_zero_means_no_retry(self) -> None:
        """With dispatch_retry_max=0, first timeout kills the step."""
        cfg = _make_config(global_max_llm_calls=0)
        cfg.agent.loop.dispatch_idle_seconds = 0.01
        cfg.agent.loop.dispatch_retry_max = 0
        cfg.agent.loop.execute_action_retry_max = 0
        executor = Executor(_make_mock_agent(), max_parallel_steps=1, config=cfg)

        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            raise DispatchTimeoutError(0.01, step_id="s0")
            yield  # pragma: no cover

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            executor._context_engine = _make_ce()
            state = LoopState(goal="g", thread_id="t-nr", iteration=0, max_iterations=4)
            step = StepAction(id="s0", description="no retry")

            results: list[Any] = []
            async for item in executor._execute_parallel([step], state):
                results.append(item)

        assert call_count == 1
        step_results = [r for r in results if isinstance(r, StepExecutionRecord)]
        assert len(step_results) == 1
        assert not step_results[0].success
