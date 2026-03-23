"""Configuration and fixtures for integration tests."""

import tempfile
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner


def pytest_addoption(parser) -> None:
    """Add custom command-line options for integration tests."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require external services",
    )


def pytest_configure(config) -> None:
    """Configure pytest markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test")


def pytest_collection_modifyitems(config, items) -> None:
    """Skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration"):
        # --run-integration given in cli: do not skip integration tests
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


def _has_valid_api_key() -> bool:
    """Check if a valid API key is available for integration tests."""
    import os

    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


@pytest.fixture
def test_config() -> SootheConfig:
    """Load config from config.dev.yml if available, otherwise use defaults.

    Returns:
        SootheConfig instance without test-specific overrides
    """
    config_path = Path(__file__).parent.parent.parent / "config.dev.yml"
    if config_path.exists():
        return SootheConfig.from_yaml_file(str(config_path))
    return SootheConfig()


@pytest.fixture
def integration_config(test_config: SootheConfig) -> SootheConfig:
    """Default config for integration tests with reduced limits.

    Args:
        test_config: Base config loaded from config.dev.yml

    Returns:
        SootheConfig with test-specific overrides
    """
    # Use smaller limits for faster testing
    test_config.execution.concurrency.max_parallel_goals = 1
    test_config.execution.concurrency.max_parallel_steps = 1
    test_config.execution.concurrency.global_max_llm_calls = 3
    test_config.autonomous.max_iterations = 5

    # Disable unified classification for tests to avoid model compatibility issues
    test_config.performance.unified_classification = False

    return test_config


@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    """Create SootheRunner with real LLM for integration tests.

    Requires OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable.

    Args:
        integration_config: Config with test-specific settings

    Yields:
        SootheRunner instance
    """
    if not _has_valid_api_key():
        pytest.skip("Integration tests require OPENAI_API_KEY or ANTHROPIC_API_KEY")

    runner = SootheRunner(integration_config)
    yield runner
    # Cleanup
    if hasattr(runner, "cleanup"):
        await runner.cleanup()


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for file operations.

    Yields:
        Path to temporary directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def web_enabled_config(test_config: SootheConfig) -> SootheConfig:
    """Config with web tools enabled.

    Args:
        test_config: Base config loaded from config.dev.yml

    Returns:
        SootheConfig with web tools enabled
    """
    from soothe.config.models import ToolsConfig

    test_config.tools = ToolsConfig(
        execution={"enabled": True},
        file_ops={"enabled": True},
        code_edit={"enabled": True},
        web_search={"enabled": True},
    )
    return test_config
