"""Configuration and fixtures for integration tests."""

from __future__ import annotations

import asyncio
import importlib
import os
import socket
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
# Shared Daemon Test Utilities
# ---------------------------------------------------------------------------

# Cache for base config to avoid repeated file reads
_CACHED_BASE_CONFIG: SootheConfig | None = None

# Track last home path to avoid unnecessary module reloads
_LAST_HOME_PATH: str | None = None


def alloc_ephemeral_port() -> int:
    """Allocate an available localhost TCP port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


def get_base_config() -> SootheConfig:
    """Get base config, loading from file once and caching the result."""
    global _CACHED_BASE_CONFIG
    if _CACHED_BASE_CONFIG is None:
        config_path = Path(__file__).parent.parent.parent / "config.dev.yml"
        _CACHED_BASE_CONFIG = (
            SootheConfig.from_yaml_file(str(config_path))
            if config_path.exists()
            else SootheConfig()
        )
    return _CACHED_BASE_CONFIG


def force_isolated_home(home: Path) -> None:
    """Force daemon paths to a test-local SOOTHE_HOME.

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

    import soothe.daemon.paths as daemon_paths

    daemon_paths.SOOTHE_HOME = home_str
    importlib.reload(daemon_paths)

    import soothe.daemon.thread_logger as daemon_thread_logger

    daemon_thread_logger.SOOTHE_HOME = home_str

    import soothe.core.thread.manager as thread_manager

    thread_manager.SOOTHE_HOME = home_str


def build_daemon_config(
    tmp_path: Path,
    websocket_port: int | None = None,
    http_port: int | None = None,
    cors_origins: list[str] | None = None,
) -> SootheConfig:
    """Build an isolated daemon config with WebSocket and HTTP REST transports (RFC-450).

    Unix socket transport was removed on 2026-03-29 due to stability issues.

    Args:
        tmp_path: Temporary path for test isolation
        websocket_port: WebSocket port (primary transport for bidirectional streaming)
        http_port: Optional HTTP REST port (for health checks and stateless CRUD)
        cors_origins: Optional CORS origins for WebSocket

    Returns:
        SootheConfig with isolated daemon configuration
    """
    base_config = get_base_config()

    daemon_config = {
        "transports": {
            "websocket": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": websocket_port or alloc_ephemeral_port(),
                "cors_origins": cors_origins or ["http://localhost:*", "http://127.0.0.1:*"],
            },
            "http_rest": {"enabled": False},
        },
    }

    if http_port is not None:
        daemon_config["transports"]["http_rest"] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": http_port,
        }

    return SootheConfig(
        providers=base_config.providers,
        router=base_config.router,
        vector_stores=base_config.vector_stores,
        vector_store_router=base_config.vector_store_router,
        persistence={"persist_dir": str(tmp_path / "persistence")},
        protocols={
            "memory": {"enabled": False},
            "durability": {"backend": "json", "persist_dir": str(tmp_path / "durability")},
        },
        daemon=daemon_config,
        performance={"unified_classification": False},
    )


async def await_event_type(readable, expected_type: str, timeout: float = 3.0) -> dict:
    """Read protocol events until a specific type is observed.

    Args:
        readable: Async callable that returns next event
        expected_type: Event type to wait for
        timeout: Maximum wait time in seconds

    Returns:
        Event dict matching expected type

    Raises:
        TimeoutError: If event not received within timeout
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Timed out waiting for event type: {expected_type}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == expected_type:
            return event


async def await_status_state(
    readable,
    expected_states: str | set[str] | tuple[str, ...],
    timeout: float = 5.0,
) -> dict:
    """Read protocol events until a status event with the expected state appears.

    Args:
        readable: Async callable that returns next event
        expected_states: State(s) to wait for (string or set of strings)
        timeout: Maximum wait time in seconds

    Returns:
        Status event dict matching expected state

    Raises:
        TimeoutError: If status not received within timeout
    """
    expected: set[str] = (
        {expected_states} if isinstance(expected_states, str) else set(expected_states)
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            states = ", ".join(sorted(expected))
            msg = f"Timed out waiting for status state: {states}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == "status" and event.get("state") in expected:
            return event


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
