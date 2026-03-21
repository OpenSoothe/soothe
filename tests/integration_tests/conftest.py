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


@pytest.fixture
def integration_config() -> SootheConfig:
    """Default config for integration tests with reduced limits."""
    config = SootheConfig()
    # Use smaller limits for faster testing
    config.execution.concurrency.max_parallel_goals = 1
    config.execution.concurrency.max_parallel_steps = 1
    config.execution.concurrency.global_max_llm_calls = 3
    config.autonomous.max_iterations = 5
    return config


@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    """Create SootheRunner with real LLM for integration tests."""
    runner = SootheRunner(integration_config)
    yield runner
    # Cleanup
    if hasattr(runner, "cleanup"):
        await runner.cleanup()


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for file operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def web_enabled_config() -> SootheConfig:
    """Config with web tools enabled."""
    from soothe.config.models import ToolsConfig

    config = SootheConfig()
    config.tools = ToolsConfig(
        execution={"enabled": True},
        file_ops={"enabled": True},
        code_edit={"enabled": True},
        web_search={"enabled": True},
    )
    return config
