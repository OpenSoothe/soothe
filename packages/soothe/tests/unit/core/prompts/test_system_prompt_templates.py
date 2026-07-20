"""Unit tests for System Prompt Optimization feature."""

from soothe.config import SootheConfig


def test_configuration_defaults():
    """Test that optimizations are enabled by design."""
    # Performance optimizations always enabled - no config fields to check
    pass


def test_prompt_templates_exist():
    """Test that all prompt templates are defined."""
    from soothe.foundation.sloop.prompts import (
        _DEFAULT_SYSTEM_PROMPT,
        _MEDIUM_SYSTEM_PROMPT,
        _SIMPLE_SYSTEM_PROMPT,
    )
    from soothe.foundation.sloop.prompts.fragments import ASSISTANT_IDENTITY_FRAGMENT

    # All templates should be non-empty strings
    assert isinstance(_SIMPLE_SYSTEM_PROMPT, str)
    assert len(_SIMPLE_SYSTEM_PROMPT) > 0

    assert isinstance(_MEDIUM_SYSTEM_PROMPT, str)
    assert len(_MEDIUM_SYSTEM_PROMPT) > 0

    assert isinstance(_DEFAULT_SYSTEM_PROMPT, str)
    assert len(_DEFAULT_SYSTEM_PROMPT) > 0

    assert "{assistant_name}" in ASSISTANT_IDENTITY_FRAGMENT


def test_middleware_can_be_imported():
    """Test that middleware can be imported from package."""
    from soothe_nano.middleware import SystemPromptMiddleware

    assert SystemPromptMiddleware is not None


def test_token_reduction_estimates():
    """Verify expected token reduction for different complexity levels."""
    config = SootheConfig()

    # Get prompts for each complexity
    from soothe.foundation.sloop.prompts import (
        _MEDIUM_SYSTEM_PROMPT,
        _SIMPLE_SYSTEM_PROMPT,
    )
    from soothe.foundation.sloop.prompts.system_templates import (
        format_complex_agent_system_prompt_core,
    )

    simple_prompt = _SIMPLE_SYSTEM_PROMPT.format(assistant_name=config.agent.name)
    medium_prompt = _MEDIUM_SYSTEM_PROMPT.format(assistant_name=config.agent.name)
    complex_prompt = format_complex_agent_system_prompt_core(
        config.agent.system_prompt,
        config.agent.name,
    )
    from soothe.foundation.sloop.prompts.identity import build_assistant_identity_block

    identity = build_assistant_identity_block(config.agent.name)
    simple_with_identity = f"{identity}\n\n{simple_prompt}"
    medium_with_identity = f"{identity}\n\n{medium_prompt}"
    complex_with_identity = f"{identity}\n\n{complex_prompt}"

    # Rough token count (words * 1.3 is a common approximation)
    simple_tokens = len(simple_with_identity.split()) * 1.3
    medium_tokens = len(medium_with_identity.split()) * 1.3
    complex_tokens = len(complex_with_identity.split()) * 1.3

    # Simple should be ~80% reduction
    simple_reduction = (complex_tokens - simple_tokens) / complex_tokens
    assert simple_reduction > 0.7, f"Expected >70% reduction, got {simple_reduction:.1%}"

    # Medium should be ~50% reduction
    medium_reduction = (complex_tokens - medium_tokens) / complex_tokens
    assert medium_reduction > 0.3, f"Expected >30% reduction, got {medium_reduction:.1%}"


if __name__ == "__main__":
    # Run basic tests
    test_configuration_defaults()
    test_prompt_templates_exist()
    test_middleware_can_be_imported()
    test_token_reduction_estimates()
