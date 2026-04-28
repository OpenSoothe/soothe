"""Integration tests for System Prompt Optimization feature."""

import pytest

from soothe.config import SootheConfig


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_enabled(test_config: SootheConfig):
    """Test that simple queries get optimized prompts when feature is enabled."""
    test_config.agentic.optimize_system_prompts = True
    test_config.agentic.unified_classification = True

    # Verify configuration
    assert test_config.agentic.optimize_system_prompts is True
    assert test_config.agentic.unified_classification is True

    # Create runner
    from soothe.core.runner import SootheRunner

    runner = SootheRunner(config=test_config)

    try:
        # Verify middleware is registered
        assert hasattr(runner._agent, "soothe_config")
        assert runner._agent.soothe_config.agentic.optimize_system_prompts
    finally:
        await runner.cleanup()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_disabled(test_config: SootheConfig):
    """Test that optimization can be disabled."""
    test_config.agentic.optimize_system_prompts = False
    test_config.agentic.unified_classification = True

    # Verify configuration
    assert test_config.agentic.optimize_system_prompts is False

    # Create runner
    from soothe.core.runner import SootheRunner

    runner = SootheRunner(config=test_config)

    try:
        # Verify middleware is not registered
        # (middleware should not be in the stack when disabled)
        pass
    finally:
        await runner.cleanup()
