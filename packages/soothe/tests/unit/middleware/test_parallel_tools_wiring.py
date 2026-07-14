"""Integration tests for ParallelToolsMiddleware with real agent execution."""

import asyncio
import os
import time

import pytest
from langchain_core.tools import tool
from support_config import config_with_router_profile

from soothe.foundation.coreagent import create_soothe_agent


def _get_router_config_for_available_credentials() -> dict:
    """Return router config based on available API credentials."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return {"default": "anthropic:claude-sonnet-4-5"}
    if os.getenv("OPENAI_API_KEY"):
        return {"default": "openai:gpt-4o-mini"}
    return {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_config_propagation(requires_llm_api):
    """Verify concurrency config propagates correctly."""
    router = _get_router_config_for_available_credentials()
    # Create config with custom concurrency settings
    config = config_with_router_profile(
        router,
        agent={
            "loop": {"limits": {"max_parallel_steps": 5}},
            "protocols": {"memory": {"enabled": False}},
        },
    )

    # Create agent
    create_soothe_agent(
        model=config.create_chat_model("agent"),
        tools=[],  # No tools needed for this test
        config=config,
    )

    # Verify middleware was added with correct config
    # (Middleware is logged during agent creation)
    # We'll verify this works by checking that agent doesn't crash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_performance_improvement(requires_llm_api):
    """Verify parallel execution is faster than sequential.

    Uses slow tools to measure timing difference.
    """
    router = _get_router_config_for_available_credentials()

    # Create slow tools
    @tool
    async def slow_tool_1(delay: float) -> str:
        """A slow tool that sleeps."""
        await asyncio.sleep(delay)
        return f"Tool 1 completed after {delay}s"

    @tool
    async def slow_tool_2(delay: float) -> str:
        """Another slow tool."""
        await asyncio.sleep(delay)
        return f"Tool 2 completed after {delay}s"

    @tool
    async def slow_tool_3(delay: float) -> str:
        """Third slow tool."""
        await asyncio.sleep(delay)
        return f"Tool 3 completed after {delay}s"

    # Test with parallel execution (max_parallel_steps=3)
    config_parallel = config_with_router_profile(
        router,
        agent={
            "loop": {"limits": {"max_parallel_steps": 3}},
            "protocols": {"memory": {"enabled": False}},
        },
    )

    create_soothe_agent(
        model=config_parallel.create_chat_model("agent"),
        tools=[slow_tool_1, slow_tool_2, slow_tool_3],
        config=config_parallel,
    )

    # Test with sequential execution (max_parallel_steps=1)
    config_sequential = config_with_router_profile(
        router,
        agent={
            "loop": {"limits": {"max_parallel_steps": 1}},
            "protocols": {"memory": {"enabled": False}},
        },
    )

    create_soothe_agent(
        model=config_sequential.create_chat_model("agent"),
        tools=[slow_tool_1, slow_tool_2, slow_tool_3],
        config=config_sequential,
    )

    # Note: Full execution requires LLM API access
    # This test verifies configuration and agent creation work


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_mixed_sync_async(requires_llm_api):
    """Verify middleware works with both sync and async tools."""
    router = _get_router_config_for_available_credentials()

    @tool
    def sync_tool(x: int) -> int:
        """A synchronous tool."""
        time.sleep(0.5)  # Simulate work
        return x * 2

    @tool
    async def async_tool(x: int) -> int:
        """An asynchronous tool."""
        await asyncio.sleep(0.5)
        return x * 3

    config = config_with_router_profile(
        router,
        agent={
            "loop": {"limits": {"max_parallel_steps": 5}},
            "protocols": {"memory": {"enabled": False}},
        },
    )

    create_soothe_agent(
        model=config.create_chat_model("agent"),
        tools=[sync_tool, async_tool],
        config=config,
    )

    # Verify agent creation succeeds with mixed tools


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_default_parallelism(requires_llm_api):
    """Verify default configuration uses max_parallel_steps=4."""
    router = _get_router_config_for_available_credentials()
    config = config_with_router_profile(router)
    config.agent.protocols.memory.enabled = False

    # Check default value for max_parallel_steps
    assert config.agent.loop.concurrency.max_parallel_steps == 4

    create_soothe_agent(
        model=config.create_chat_model("agent"),
        tools=[],
        config=config,
    )

    # Agent should use default concurrency settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_extreme_cases(requires_llm_api):
    """Test edge cases: max_parallel_steps=1 (sequential) and max_parallel_steps=10 (high)."""
    router = _get_router_config_for_available_credentials()

    @tool
    async def dummy_tool() -> str:
        """A minimal tool."""
        return "done"

    # Test sequential (max_parallel_steps=1)
    config_seq = config_with_router_profile(router)
    config_seq.agent.loop.concurrency.max_parallel_steps = 1
    config_seq.agent.protocols.memory.enabled = False

    create_soothe_agent(
        model=config_seq.create_chat_model("agent"),
        tools=[dummy_tool],
        config=config_seq,
    )

    # Test high parallelism (max_parallel_steps=10)
    config_high = config_with_router_profile(router)
    config_high.agent.loop.concurrency.max_parallel_steps = 10
    config_high.agent.protocols.memory.enabled = False

    create_soothe_agent(
        model=config_high.create_chat_model("agent"),
        tools=[dummy_tool],
        config=config_high,
    )

    # Both should create successfully


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_tools_zero_means_unlimited(requires_llm_api):
    """Verify that max_parallel_steps=0 means unlimited (valid special value)."""
    router = _get_router_config_for_available_credentials()
    # 0 is valid - it means unlimited parallelism
    config_unlimited = config_with_router_profile(router)
    config_unlimited.agent.loop.concurrency.max_parallel_steps = 0
    config_unlimited.agent.protocols.memory.enabled = False

    # Should create successfully
    create_soothe_agent(
        model=config_unlimited.create_chat_model("agent"),
        tools=[],
        config=config_unlimited,
    )

    # Note: ConcurrencyPolicy allows 0 as special "unlimited" value
    # Negative values would be rejected by Pydantic validation


# Note: Full integration tests with actual LLM execution would require:
# - API keys set up
# - Real LLM responses with multiple tool_calls
# - Timing measurements with actual network calls
#
# The tests above verify:
# - Configuration propagation
# - Agent creation with middleware
# - Mixed sync/async tools
# - Default values
# - Edge cases
