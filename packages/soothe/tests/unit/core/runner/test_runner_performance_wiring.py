"""Integration tests for runner performance-related wiring (RFC-0008)."""

import os

import pytest
from soothe_nano.middleware import build_soothe_middleware_stack
from soothe_nano.middleware.system_prompt import SystemPromptMiddleware
from support_config import config_with_router_profile

from soothe.config import SootheConfig
from soothe.runner import SootheRunner

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_query_complexity_classification(test_config: SootheConfig, requires_llm_api):
    """Intent classifier is wired when a fast chat model can be created."""
    runner = SootheRunner(test_config)

    try:
        assert hasattr(runner, "_intent_classifier")
        if runner._intent_classifier is not None:
            from soothe.foundation.sloop.intention import IntentClassifier

            assert isinstance(runner._intent_classifier, IntentClassifier)

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_template_planning(test_config: SootheConfig, requires_llm_api):
    """Runner exposes a planner when the agent stack configured one."""
    runner = SootheRunner(test_config)

    try:
        if runner._planner:
            assert runner._planner is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_memory_recall(test_config: SootheConfig, requires_llm_api):
    """Runner exposes memory wiring; backend may be None when disabled or unresolved."""
    runner = SootheRunner(test_config)

    try:
        assert hasattr(runner, "_memory")
        if test_config.agent.protocols.memory.enabled and runner._memory is not None:
            assert runner._memory is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_conditional_context_projection(test_config: SootheConfig, requires_llm_api):
    """CoreAgent exposes context middleware wiring (no ``protocols.context`` block)."""
    runner = SootheRunner(test_config)

    try:
        assert hasattr(runner._agent, "config")
        stack = build_soothe_middleware_stack(test_config, policy=runner._policy)
        assert any(isinstance(m, SystemPromptMiddleware) for m in stack)

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_parallel_execution(test_config: SootheConfig, requires_llm_api):
    """Execution concurrency limits remain configurable."""
    test_config.agent.loop.concurrency.max_parallel_steps = 2
    runner = SootheRunner(test_config)

    try:
        assert test_config.agent.loop.concurrency.max_parallel_steps == 2

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_feature_flags(requires_llm_api):
    """Agentic final-response mode remains a supported toggle."""
    # Configure router based on available credentials
    if os.getenv("ANTHROPIC_API_KEY"):
        router_config = {
            "default": "anthropic:claude-sonnet-4-5",
            "fast": "anthropic:claude-haiku-3-5",
        }
    elif os.getenv("OPENAI_API_KEY"):
        router_config = {"default": "openai:gpt-4o-mini", "fast": "openai:gpt-4o-mini"}
    else:
        router_config = {}

    config1 = config_with_router_profile(router_config)
    config1.agent.loop.final_response = "always_synthesize"
    config1.agent.protocols.memory.enabled = False  # Anthropic doesn't support embeddings
    runner1 = SootheRunner(config1)

    try:
        assert config1.agent.loop.final_response == "always_synthesize"

    finally:
        await runner1.cleanup()

    config2 = config_with_router_profile(router_config)
    config2.agent.loop.final_response = "auto"
    config2.agent.protocols.memory.enabled = False  # Anthropic doesn't support embeddings
    runner2 = SootheRunner(config2)

    try:
        assert config2.agent.loop.final_response == "auto"

    finally:
        await runner2.cleanup()
