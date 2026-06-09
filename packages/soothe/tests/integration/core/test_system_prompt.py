"""Integration tests for system prompt optimization middleware (always-on)."""

import pytest

from soothe.config import SootheConfig
from soothe.runner import SootheRunner
from soothe.middleware import build_soothe_middleware_stack
from soothe.middleware.system_prompt import SystemPromptMiddleware


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_enabled(test_config: SootheConfig):
    """System prompt optimization middleware is always present on the Soothe stack."""
    stack = build_soothe_middleware_stack(test_config, policy=None)
    assert any(isinstance(m, SystemPromptMiddleware) for m in stack)

    runner = SootheRunner(config=test_config)

    try:
        assert runner._agent is not None
        assert runner._agent.config is test_config
    finally:
        await runner.cleanup()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_prompt_optimization_disabled(test_config: SootheConfig):
    """No config flag disables optimization; stack remains unchanged (regression guard)."""
    stack = build_soothe_middleware_stack(test_config, policy=None)
    opt = [m for m in stack if isinstance(m, SystemPromptMiddleware)]
    assert len(opt) == 1

    runner = SootheRunner(config=test_config)
    try:
        assert runner._agent.config is test_config
    finally:
        await runner.cleanup()
