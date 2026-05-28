"""Configuration and fixtures for integration tests."""

from __future__ import annotations

import os
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
    config.addinivalue_line("markers", "slow: long-running or stress tests")
    config.addinivalue_line("markers", "requires_postgresql: requires PostgreSQL database")
    config.addinivalue_line("markers", "requires_llm_api: requires LLM API keys")


def pytest_collection_modifyitems(config, items) -> None:
    """Skip tests marked ``integration`` unless ``--run-integration`` is passed.

    Use ``get_closest_marker("integration")`` only: ``item.keywords`` also contains
    the parent package name ``integration``, which would skip every test under
    ``tests/integration/`` even when the module is not marked.
    """
    if config.getoption("--run-integration"):
        # --run-integration given in cli: do not skip integration tests
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# External Service Availability Checks
# ---------------------------------------------------------------------------


def _has_postgresql() -> bool:
    """Check if PostgreSQL database is available for integration tests."""
    # Check for PostgreSQL connection parameters
    has_postgres_host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST")
    has_postgres_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    return bool(has_postgres_host or has_postgres_url)


def _has_valid_api_key() -> bool:
    """Check if a valid LLM API key is available for integration tests."""
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )


# Cache for base config to avoid repeated file reads
_CACHED_BASE_CONFIG: SootheConfig | None = None

# Track last home path to avoid unnecessary module reloads
_LAST_HOME_PATH: str | None = None


def get_base_config() -> SootheConfig:
    """Get base config, loading from file once and caching the result.

    Resolution order:
        1. ``SOOTHE_INTEGRATION_BASE_CONFIG`` — explicit path (e.g. explore-only YAML).
        2. Repo ``config/config.dev.yml`` (monorepo root = parents[4] of this file).
        3. Empty :class:`SootheConfig` if no file exists.
    """
    global _CACHED_BASE_CONFIG
    if _CACHED_BASE_CONFIG is None:
        env_path = os.environ.get("SOOTHE_INTEGRATION_BASE_CONFIG", "").strip()
        if env_path:
            p = Path(env_path).expanduser()
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(p)) if p.is_file() else SootheConfig()
            )
        else:
            repo_root = Path(__file__).resolve().parents[4]
            config_path = repo_root / "config" / "config.dev.yml"
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(config_path))
                if config_path.is_file()
                else SootheConfig()
            )
    return _CACHED_BASE_CONFIG


def force_isolated_home(home: Path) -> None:
    """Force Soothe paths to a test-local SOOTHE_HOME.

    Only reloads modules if home path has changed.
    """
    global _LAST_HOME_PATH

    home_str = str(home)
    if _LAST_HOME_PATH == home_str:
        return  # Skip if already set to this path

    _LAST_HOME_PATH = home_str
    os.environ["SOOTHE_HOME"] = home_str

    import soothe.config as soothe_config
    from soothe import config as config_module

    soothe_config.SOOTHE_HOME = home_str
    config_module.SOOTHE_HOME = home_str

    import soothe.core.thread.manager as thread_manager

    thread_manager.SOOTHE_HOME = home_str


# ---------------------------------------------------------------------------
# Service Availability Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def requires_postgresql():
    """Fixture that skips test if PostgreSQL is not available."""
    if not _has_postgresql():
        pytest.skip(
            "Test requires PostgreSQL (set POSTGRES_HOST, POSTGRES_URL, PGHOST, or DATABASE_URL)"
        )


@pytest.fixture
def requires_llm_api():
    """Fixture that skips test if LLM API key is not available."""
    if not _has_valid_api_key():
        pytest.skip(
            "Test requires LLM API key (set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "or DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL)"
        )


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


def _has_valid_api_key() -> bool:
    """Check if a valid API key is available for integration tests."""
    import os

    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )


@pytest.fixture
def test_config() -> SootheConfig:
    """Deep copy of base integration config so per-test mutations cannot poison the cache."""
    return get_base_config().model_copy(deep=True)


@pytest.fixture
def integration_config(test_config: SootheConfig) -> SootheConfig:
    """Default config for integration tests with reduced limits.

    Args:
        test_config: Base config loaded from config.dev.yml

    Returns:
        SootheConfig with test-specific overrides
    """
    # Use smaller limits for faster testing
    test_config.agent.loop.limits.max_parallel_goals = 1
    test_config.agent.loop.limits.max_parallel_steps = 1
    test_config.agent.loop.limits.global_max_llm_calls = 3
    test_config.agent.autonomous.max_iterations = 5

    return test_config


@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    """Create SootheRunner with real LLM for integration tests.

    Requires OPENAI_API_KEY, ANTHROPIC_API_KEY, or Dashscope credentials
    (DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL) environment variable.

    Args:
        integration_config: Config with test-specific settings

    Yields:
        SootheRunner instance
    """
    if not _has_valid_api_key():
        pytest.skip(
            "Integration tests require OPENAI_API_KEY, ANTHROPIC_API_KEY, or Dashscope credentials"
        )

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
