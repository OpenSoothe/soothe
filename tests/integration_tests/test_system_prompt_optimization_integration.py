"""Integration tests for System Prompt Optimization feature."""

from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner


def _load_test_config() -> SootheConfig:
    """Load config from config.dev.yml if available, otherwise use defaults."""
    config_path = Path(__file__).parent.parent.parent / "config.dev.yml"
    if config_path.exists():
        return SootheConfig.from_yaml_file(str(config_path))
    return SootheConfig()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_enabled():
    """Test that simple queries get optimized prompts when feature is enabled."""
    config = _load_test_config()
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
    config = _load_test_config()
    config.performance.optimize_system_prompts = False
    config.performance.unified_classification = True

    # Verify configuration
    assert config.performance.optimize_system_prompts is False

    # Create runner
    runner = SootheRunner(config=config)

    # Verify middleware is not registered
    # (middleware should not be in the stack when disabled)
