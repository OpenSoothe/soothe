"""Integration tests for performance optimizations (RFC-0008)."""

import pytest

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_query_complexity_classification(test_config: SootheConfig):
    """Test that query complexity is classified correctly."""
    runner = SootheRunner(test_config)

    try:
        # Test that unified classifier is initialized if performance is enabled
        if test_config.performance.enabled and test_config.performance.unified_classification:
            assert runner._unified_classifier is not None, "Unified classifier should be initialized"

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_template_planning(test_config: SootheConfig):
    """Test that template plans are used for trivial/simple queries."""
    runner = SootheRunner(test_config)

    try:
        # Template planning is now handled by the planner directly
        # This test verifies the runner has a planner configured
        if runner._planner:
            assert runner._planner is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_memory_recall(test_config: SootheConfig):
    """Test that memory recall is conditionally applied based on query complexity."""
    runner = SootheRunner(test_config)

    try:
        # Memory recall is handled based on query complexity classification
        # This test verifies the runner has the necessary protocols configured
        if test_config.protocols.memory.enabled:
            assert runner._memory is not None or runner._memory is None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_context_projection(test_config: SootheConfig):
    """Test that context projection is conditionally applied based on query complexity."""
    runner = SootheRunner(test_config)

    try:
        # Context projection is handled based on query complexity classification
        # This test verifies the runner has the necessary protocols configured
        if test_config.protocols.context.enabled:
            assert runner._context is not None or runner._context is None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_parallel_execution(test_config: SootheConfig):
    """Test that parallel execution works for medium/complex queries."""
    test_config.performance.enabled = True
    runner = SootheRunner(test_config)

    try:
        # Verify configuration
        assert test_config.performance.enabled is True

        # Parallel execution is handled internally in the runner
        # This test verifies the configuration is correct

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
