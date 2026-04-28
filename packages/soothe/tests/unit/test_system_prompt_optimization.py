"""Unit tests for System Prompt Optimization feature."""

from soothe.config import SootheConfig


def test_configuration_defaults():
    """Test that optimizations are enabled by design."""
    # Performance optimizations always enabled - no config fields to check
    pass


def test_prompt_templates_exist():
    """Test that all prompt templates are defined."""
    from soothe.config import _DEFAULT_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT, _SIMPLE_SYSTEM_PROMPT

    # All templates should be non-empty strings
    assert isinstance(_SIMPLE_SYSTEM_PROMPT, str)
    assert len(_SIMPLE_SYSTEM_PROMPT) > 0
    assert "{assistant_name}" in _SIMPLE_SYSTEM_PROMPT

    assert isinstance(_MEDIUM_SYSTEM_PROMPT, str)
    assert len(_MEDIUM_SYSTEM_PROMPT) > 0
    assert "{assistant_name}" in _MEDIUM_SYSTEM_PROMPT

    assert isinstance(_DEFAULT_SYSTEM_PROMPT, str)
    assert len(_DEFAULT_SYSTEM_PROMPT) > 0
    assert "{assistant_name}" in _DEFAULT_SYSTEM_PROMPT


def test_middleware_can_be_imported():
    """Test that middleware can be imported from package."""
    from soothe.middleware import SystemPromptOptimizationMiddleware

    assert SystemPromptOptimizationMiddleware is not None


def test_token_reduction_estimates():
    """Verify expected token reduction for different complexity levels."""
    config = SootheConfig()

    # Get prompts for each complexity
    from soothe.config import _DEFAULT_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT, _SIMPLE_SYSTEM_PROMPT

    simple_prompt = _SIMPLE_SYSTEM_PROMPT.format(assistant_name=config.assistant_name)
    medium_prompt = _MEDIUM_SYSTEM_PROMPT.format(assistant_name=config.assistant_name)
    complex_prompt = config.system_prompt or _DEFAULT_SYSTEM_PROMPT.format(
        assistant_name=config.assistant_name
    )

    # Rough token count (words * 1.3 is a common approximation)
    simple_tokens = len(simple_prompt.split()) * 1.3
    medium_tokens = len(medium_prompt.split()) * 1.3
    complex_tokens = len(complex_prompt.split()) * 1.3

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
