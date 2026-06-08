"""Unit tests for Tacitus parallel source gathering and timeout behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.subagents.tacitus.engine import _gather_from_sources_parallel
from soothe.subagents.tacitus.protocol import GatherContext, SourceResult


@pytest.fixture
def gather_context() -> GatherContext:
    """Default gather context for tests."""
    return GatherContext(topic="test query")


class TestParallelSourceGathering:
    """Tests for concurrent source execution."""

    async def test_gather_queries_all_sources_concurrently(self, gather_context: GatherContext):
        """All sources should be queried in parallel, not sequentially."""
        # Track call times to verify parallel execution
        call_times: list[tuple[str, float]] = []

        async def slow_query(query: str, context: GatherContext) -> list[SourceResult]:
            call_times.append(("start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)  # Simulate network delay
            call_times.append(("end", asyncio.get_event_loop().time()))
            return [
                SourceResult(
                    content=f"Result from {query}",
                    source_ref="https://example.com",
                    source_name="mock",
                )
            ]

        # Create 3 mock sources
        sources = []
        for i in range(3):
            src = MagicMock()
            src.name = f"source_{i}"
            src.query = AsyncMock(side_effect=slow_query)
            sources.append(src)

        # Execute parallel gather
        results = await _gather_from_sources_parallel(
            sources, "test query", gather_context, timeout_sec=5.0
        )

        # All sources should have been called
        for src in sources:
            src.query.assert_called_once_with("test query", gather_context)

        # Should have results from all sources
        assert len(results) == 3

        # Verify parallel execution: all sources should start within a short window
        # If sequential, starts would be ~0.1s apart; if parallel, starts are concurrent
        start_times = [t for label, t in call_times if label == "start"]
        assert len(start_times) == 3, "All 3 sources should have started"
        # All sources should start within 0.05s of each other (parallel window)
        start_window = max(start_times) - min(start_times)
        assert start_window < 0.05, (
            f"Sources did not start concurrently (window={start_window:.3f}s)"
        )

    async def test_gather_aggregates_results_from_all_sources(self, gather_context: GatherContext):
        """Results from multiple sources should be aggregated."""

        async def source_a_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [
                SourceResult(content="A1", source_ref="ref1", source_name="a"),
                SourceResult(content="A2", source_ref="ref2", source_name="a"),
            ]

        async def source_b_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="B1", source_ref="ref3", source_name="b")]

        source_a = MagicMock()
        source_a.name = "source_a"
        source_a.query = AsyncMock(side_effect=source_a_query)

        source_b = MagicMock()
        source_b.name = "source_b"
        source_b.query = AsyncMock(side_effect=source_b_query)

        results = await _gather_from_sources_parallel(
            [source_a, source_b], "test", gather_context, timeout_sec=5.0
        )

        # Should have all results aggregated
        assert len(results) == 3
        assert sum(1 for r in results if r.source_name == "a") == 2
        assert sum(1 for r in results if r.source_name == "b") == 1

    async def test_gather_handles_empty_results(self, gather_context: GatherContext):
        """Sources returning empty results should not break aggregation."""

        async def empty_query(query: str, context: GatherContext) -> list[SourceResult]:
            return []

        async def results_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="Found", source_ref="ref", source_name="has_results")]

        source_empty = MagicMock()
        source_empty.name = "empty"
        source_empty.query = AsyncMock(side_effect=empty_query)

        source_results = MagicMock()
        source_results.name = "results"
        source_results.query = AsyncMock(side_effect=results_query)

        results = await _gather_from_sources_parallel(
            [source_empty, source_results], "test", gather_context, timeout_sec=5.0
        )

        assert len(results) == 1
        assert results[0].content == "Found"


class TestSourceTimeoutBehavior:
    """Tests for per-source timeout handling."""

    async def test_slow_source_times_out(self, gather_context: GatherContext):
        """Sources exceeding timeout should return empty results."""

        async def slow_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(2.0)  # Will exceed 0.1s timeout
            return [SourceResult(content="Too late", source_ref="ref", source_name="slow")]

        async def fast_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="Fast", source_ref="ref", source_name="fast")]

        source_slow = MagicMock()
        source_slow.name = "slow"
        source_slow.query = AsyncMock(side_effect=slow_query)

        source_fast = MagicMock()
        source_fast.name = "fast"
        source_fast.query = AsyncMock(side_effect=fast_query)

        results = await _gather_from_sources_parallel(
            [source_slow, source_fast], "test", gather_context, timeout_sec=0.1
        )

        # Fast source should return results, slow should timeout
        assert len(results) == 1
        assert results[0].content == "Fast"

    async def test_timeout_does_not_block_other_sources(self, gather_context: GatherContext):
        """A timing out source should not block other sources."""

        async def very_slow_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(10.0)
            return []

        async def fast_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(0.05)
            return [SourceResult(content="Fast result", source_ref="ref", source_name="fast")]

        source_slow = MagicMock()
        source_slow.name = "slow"
        source_slow.query = AsyncMock(side_effect=very_slow_query)

        source_fast = MagicMock()
        source_fast.name = "fast"
        source_fast.query = AsyncMock(side_effect=fast_query)

        start = asyncio.get_event_loop().time()
        results = await _gather_from_sources_parallel(
            [source_slow, source_fast], "test", gather_context, timeout_sec=0.1
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Should complete quickly (fast source + timeout), not wait for slow
        assert elapsed < 0.3
        assert len(results) == 1

    async def test_all_sources_timeout(self, gather_context: GatherContext):
        """When all sources timeout, should return empty list."""

        async def slow_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(1.0)
            return []

        sources = []
        for i in range(3):
            src = MagicMock()
            src.name = f"source_{i}"
            src.query = AsyncMock(side_effect=slow_query)
            sources.append(src)

        results = await _gather_from_sources_parallel(
            sources, "test", gather_context, timeout_sec=0.05
        )

        assert results == []


class TestSourceErrorHandling:
    """Tests for error handling in parallel gathering."""

    async def test_exception_in_one_source_does_not_fail_others(
        self, gather_context: GatherContext
    ):
        """An exception in one source should not prevent others from returning."""

        async def failing_query(query: str, context: GatherContext) -> list[SourceResult]:
            raise ValueError("Simulated failure")

        async def working_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="Success", source_ref="ref", source_name="working")]

        source_failing = MagicMock()
        source_failing.name = "failing"
        source_failing.query = AsyncMock(side_effect=failing_query)

        source_working = MagicMock()
        source_working.name = "working"
        source_working.query = AsyncMock(side_effect=working_query)

        results = await _gather_from_sources_parallel(
            [source_failing, source_working], "test", gather_context, timeout_sec=5.0
        )

        # Working source should still return results
        assert len(results) == 1
        assert results[0].content == "Success"

    async def test_all_sources_fail_returns_empty(self, gather_context: GatherContext):
        """When all sources fail, should return empty list."""

        async def failing_query(query: str, context: GatherContext) -> list[SourceResult]:
            raise RuntimeError("All sources failed")

        sources = []
        for i in range(3):
            src = MagicMock()
            src.name = f"source_{i}"
            src.query = AsyncMock(side_effect=failing_query)
            sources.append(src)

        results = await _gather_from_sources_parallel(
            sources, "test", gather_context, timeout_sec=5.0
        )

        assert results == []

    async def test_mixed_results_errors_and_success(self, gather_context: GatherContext):
        """Mix of errors, timeouts, and successes should aggregate correctly."""

        async def error_query(query: str, context: GatherContext) -> list[SourceResult]:
            raise ValueError("Error")

        async def timeout_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(10.0)
            return []

        async def success_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="Success", source_ref="ref", source_name="success")]

        source_error = MagicMock()
        source_error.name = "error"
        source_error.query = AsyncMock(side_effect=error_query)

        source_timeout = MagicMock()
        source_timeout.name = "timeout"
        source_timeout.query = AsyncMock(side_effect=timeout_query)

        source_success = MagicMock()
        source_success.name = "success"
        source_success.query = AsyncMock(side_effect=success_query)

        results = await _gather_from_sources_parallel(
            [source_error, source_timeout, source_success],
            "test",
            gather_context,
            timeout_sec=0.1,
        )

        # Only success source should contribute
        assert len(results) == 1
        assert results[0].content == "Success"


class TestEdgeCases:
    """Edge case tests for parallel gathering."""

    async def test_empty_source_list(self, gather_context: GatherContext):
        """Empty source list should return empty results."""
        results = await _gather_from_sources_parallel([], "test", gather_context, timeout_sec=5.0)
        assert results == []

    async def test_single_source(self, gather_context: GatherContext):
        """Single source should work correctly."""

        async def single_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [SourceResult(content="Single", source_ref="ref", source_name="single")]

        source = MagicMock()
        source.name = "single"
        source.query = AsyncMock(side_effect=single_query)

        results = await _gather_from_sources_parallel(
            [source], "test", gather_context, timeout_sec=5.0
        )

        assert len(results) == 1
        assert results[0].content == "Single"

    async def test_source_returns_multiple_results(self, gather_context: GatherContext):
        """Sources returning multiple results should all be included."""

        async def multi_query(query: str, context: GatherContext) -> list[SourceResult]:
            return [
                SourceResult(content="R1", source_ref="ref1", source_name="multi"),
                SourceResult(content="R2", source_ref="ref2", source_name="multi"),
                SourceResult(content="R3", source_ref="ref3", source_name="multi"),
            ]

        source = MagicMock()
        source.name = "multi"
        source.query = AsyncMock(side_effect=multi_query)

        results = await _gather_from_sources_parallel(
            [source], "test", gather_context, timeout_sec=5.0
        )

        assert len(results) == 3

    @pytest.mark.parametrize("timeout", [0.001, 0.01, 0.1, 1.0, 10.0])
    async def test_various_timeout_values(self, timeout: float, gather_context: GatherContext):
        """Different timeout values should be respected."""

        async def slow_query(query: str, context: GatherContext) -> list[SourceResult]:
            await asyncio.sleep(0.5)  # Always slower than short timeouts
            return [SourceResult(content="Late", source_ref="ref", source_name="slow")]

        source = MagicMock()
        source.name = "slow"
        source.query = AsyncMock(side_effect=slow_query)

        start = asyncio.get_event_loop().time()
        results = await _gather_from_sources_parallel(
            [source], "test", gather_context, timeout_sec=timeout
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Should complete near the timeout, not wait for slow query
        if timeout < 0.5:
            assert elapsed < timeout + 0.1
            assert results == []
        else:
            # Timeout longer than query, should get results
            assert len(results) == 1
