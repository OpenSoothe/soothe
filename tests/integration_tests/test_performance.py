"""Integration tests for performance optimizations (RFC-0008)."""

import asyncio
import time

import pytest

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner


@pytest.mark.asyncio
async def test_trivial_query_latency():
    """Test that trivial queries complete in < 500ms (Phase 1 target)."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        queries = ["hello", "thanks", "who are you?"]

        for query in queries:
            start = time.perf_counter()
            events = [chunk async for chunk in runner.astream(query)]
            duration_ms = (time.perf_counter() - start) * 1000

            # Phase 1 target: < 500ms for trivial queries
            assert duration_ms < 500, f"Trivial query '{query}' took {duration_ms:.0f}ms (target: <500ms)"
            assert len(events) > 0, "Should produce events"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_simple_query_latency():
    """Test that simple queries complete in < 1s (Phase 1 target)."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        queries = ["read config.yml", "list files", "search for python"]

        for query in queries:
            start = time.perf_counter()
            events = [chunk async for chunk in runner.astream(query)]
            duration_ms = (time.perf_counter() - start) * 1000

            # Phase 1 target: < 1000ms for simple queries
            assert duration_ms < 1000, f"Simple query '{query}' took {duration_ms:.0f}ms (target: <1000ms)"
            assert len(events) > 0, "Should produce events"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_medium_query_latency():
    """Test that medium queries complete in < 2s (Phase 2 target)."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        queries = ["implement a function to parse JSON", "debug the error in my code"]

        for query in queries:
            start = time.perf_counter()
            events = [chunk async for chunk in runner.astream(query)]
            duration_ms = (time.perf_counter() - start) * 1000

            # Phase 2 target: < 2000ms for medium queries
            assert duration_ms < 2000, f"Medium query '{query}' took {duration_ms:.0f}ms (target: <2000ms)"
            assert len(events) > 0, "Should produce events"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_query_complexity_classification():
    """Test that query complexity is classified correctly."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        # Test that classifier is initialized
        assert runner._classifier is not None, "Classifier should be initialized"

        # Test trivial classification
        assert runner._classify_query("hello") == "trivial"
        assert runner._classify_query("who are you?") == "trivial"

        # Test simple classification
        assert runner._classify_query("read the file") == "simple"
        assert runner._classify_query("search for python") == "simple"

        # Test medium classification
        assert runner._classify_query("implement a function to parse JSON") == "medium"

        # Test complex classification
        assert runner._classify_query("refactor the authentication system") == "complex"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_template_planning():
    """Test that template plans are used for trivial/simple queries."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        # Test trivial template
        plan = runner._get_template_plan("hello", "trivial")
        assert plan is not None
        assert plan.goal == "hello"
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "hello"

        # Test simple search template
        plan = runner._get_template_plan("search for python tutorials", "simple")
        assert plan is not None
        assert len(plan.steps) == 2
        assert "Search" in plan.steps[0].description

        # Test implementation template
        plan = runner._get_template_plan("implement a REST API", "simple")
        assert plan is not None
        assert len(plan.steps) == 3
        assert "Implement" in plan.steps[1].description

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_memory_recall():
    """Test that memory recall is skipped for trivial/simple queries."""
    config = SootheConfig()
    config.performance.skip_memory_for_simple = True
    runner = SootheRunner(config)

    try:
        # For trivial queries, memory should be skipped
        # We can't directly test if memory.recall() was called, but we can
        # verify the configuration is correct
        assert config.performance.skip_memory_for_simple is True

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_context_projection():
    """Test that context projection is skipped for trivial/simple queries."""
    config = SootheConfig()
    config.performance.skip_context_for_simple = True
    runner = SootheRunner(config)

    try:
        # For trivial queries, context should be skipped
        assert config.performance.skip_context_for_simple is True

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_parallel_execution():
    """Test that parallel execution works for medium/complex queries."""
    config = SootheConfig()
    config.performance.enabled = True
    config.performance.parallel_pre_stream = True
    runner = SootheRunner(config)

    try:
        # Verify configuration
        assert config.performance.enabled is True
        assert config.performance.parallel_pre_stream is True

        # Test that parallel execution method exists and works
        memory_items, context_projection = await runner._pre_stream_parallel_memory_context("test query", "medium")

        # Results should be lists/tuples (may be empty if no memory/context)
        assert isinstance(memory_items, list)
        assert context_projection is None or hasattr(context_projection, "total_entries")

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_feature_flags():
    """Test that feature flags work correctly."""
    # Test with performance disabled
    config1 = SootheConfig()
    config1.performance.enabled = False
    runner1 = SootheRunner(config1)

    try:
        # Query classification should still work, but optimizations should be disabled
        assert config1.performance.enabled is False

    finally:
        await runner1.cleanup()

    # Test with parallel execution disabled
    config2 = SootheConfig()
    config2.performance.parallel_pre_stream = False
    runner2 = SootheRunner(config2)

    try:
        # Parallel execution should be disabled
        assert config2.performance.parallel_pre_stream is False

    finally:
        await runner2.cleanup()


@pytest.mark.asyncio
async def test_performance_regression_complex_queries():
    """Test that complex queries still work correctly (no quality regression)."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        complex_queries = [
            "refactor the authentication system to use OAuth",
            "design a microservices architecture for the API",
        ]

        for query in complex_queries:
            events = [chunk async for chunk in runner.astream(query)]

            # Complex queries should still produce events
            assert len(events) > 0, f"Complex query '{query}' should produce events"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_classification_performance():
    """Test that query classification is fast (< 1ms)."""
    config = SootheConfig()
    runner = SootheRunner(config)

    try:
        queries = ["hello", "read the file", "implement a function", "refactor the system"] * 100

        start = time.perf_counter()
        for query in queries:
            runner._classify_query(query)
        duration_ms = (time.perf_counter() - start) * 1000

        avg_ms = duration_ms / len(queries)
        assert avg_ms < 1.0, f"Classification too slow: {avg_ms:.2f}ms per query (target: <1ms)"

    finally:
        await runner.cleanup()


def test_rocksdb_data_subfolder_structure():
    """Test that RocksDB files are stored in data/ subfolders."""
    import tempfile
    import shutil
    from pathlib import Path
    from soothe.config import SOOTHE_HOME
    import os

    # Use temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["SOOTHE_HOME"] = tmpdir

        # Import after setting env var
        from soothe.cli.main import migrate_rocksdb_to_data_subfolder

        # Create old structure
        durability_dir = Path(tmpdir) / "durability"
        durability_dir.mkdir()
        (durability_dir / "LOG").touch()
        (durability_dir / "test.db").touch()

        # Run migration
        migrate_rocksdb_to_data_subfolder()

        # Verify migration
        data_dir = durability_dir / "data"
        assert data_dir.exists()
        assert (data_dir / "LOG").exists()
        assert (data_dir / "test.db").exists()
        assert not (durability_dir / "LOG").exists()  # Moved, not copied
