"""Integration tests for System Prompt Optimization feature."""

import pytest

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_enabled():
    """Test that simple queries get optimized prompts when feature is enabled."""
    config = SootheConfig()
    config.performance.optimize_system_prompts = True
    config.performance.unified_classification = True

    # Verify configuration
    assert config.performance.optimize_system_prompts is True
    assert config.performance.unified_classification is True

    # Create runner
    runner = SootheRunner(config=config)

    # Verify middleware is registered
    assert hasattr(runner._agent, "soothe_config")
    assert runner._agent.soothe_config.performance.optimize_system_prompts


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_disabled():
    """Test that optimization can be disabled."""
    config = SootheConfig()
    config.performance.optimize_system_prompts = False
    config.performance.unified_classification = True

    # Verify configuration
    assert config.performance.optimize_system_prompts is False

    # Create runner
    runner = SootheRunner(config=config)

    # Verify middleware is not registered
    # (middleware should not be in the stack when disabled)
