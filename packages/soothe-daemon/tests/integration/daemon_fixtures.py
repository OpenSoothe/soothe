"""Configuration and fixtures for integration tests."""

from __future__ import annotations

import asyncio
import importlib
import os
import socket
import tempfile
from pathlib import Path
from typing import Any

import pytest
from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner

from soothe_daemon.config import SootheDaemonConfig


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


def integration_llm_idle_timeout() -> float:
    """Seconds to wait for daemon idle after an LLM-backed turn (override via env)."""
    raw = os.getenv("SOOTHE_INTEGRATION_LLM_IDLE_TIMEOUT", "180").strip()
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 90.0


@pytest.fixture
def llm_idle_timeout() -> float:
    """Fixture exposing :func:`integration_llm_idle_timeout` for slow LLM integration tests."""
    return integration_llm_idle_timeout()


# ---------------------------------------------------------------------------
# Shared Daemon Test Utilities
# ---------------------------------------------------------------------------


async def websocket_bootstrap_loop_session(
    client: Any,
    *,
    resume_loop_id: str | None = None,
) -> str:
    """Create or attach to a loop and subscribe for streaming; returns ``loop_id``."""
    from soothe_sdk.client.session import bootstrap_loop_session

    ev = await bootstrap_loop_session(
        client,
        resume_loop_id=resume_loop_id,
    )
    if ev.get("type") == "error" or not ev.get("success", True):
        raise RuntimeError(str(ev.get("message", "loop bootstrap failed")))
    lid = ev.get("loop_id")
    if not lid:
        raise RuntimeError("bootstrap missing loop_id")
    return str(lid)


async def websocket_create_loop_only(client: Any, *, timeout: float = 10.0) -> str:
    """Allocate a new ``loop_id`` without ``loop_subscribe`` (unsubscribed client tests)."""
    await client.request_daemon_ready()
    await client.wait_for_daemon_ready()
    resp = await client.request_response(
        {"type": "loop_new"},
        response_type="loop_new_response",
        timeout=timeout,
    )
    lid = str(resp.get("loop_id") or "").strip()
    if not lid:
        raise RuntimeError("loop_new_response missing loop_id")
    return lid


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

    soothe_config.SOOTHE_HOME = Path(home_str)
    config_module.SOOTHE_HOME = Path(home_str)

    import soothe_daemon.bootstrap.paths as daemon_paths

    daemon_paths.SOOTHE_HOME = Path(home_str)
    importlib.reload(daemon_paths)

    import soothe.core.thread.manager as thread_manager

    thread_manager.SOOTHE_HOME = Path(home_str)

    import soothe_sdk.client.config as sdk_config

    sdk_config.SOOTHE_HOME = Path(home_str)
    sdk_config.SOOTHE_DATA_DIR = str(Path(home_str) / "data")


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


def build_daemon_config(
    tmp_path: Path,
    websocket_port: int | None = None,
    http_port: int | None = None,
    cors_origins: list[str] | None = None,
) -> tuple[SootheConfig, SootheDaemonConfig]:
    """Build isolated agent and daemon server configs (RFC-450).

    ``SootheConfig`` intentionally omits a ``daemon:`` block (it is stripped at
    validation). Pass the returned :class:`SootheDaemonConfig` as
    ``SootheDaemon(..., daemon_config=...)``.

    Args:
        tmp_path: Temporary path for test isolation
        websocket_port: WebSocket port (primary transport for bidirectional streaming)
        http_port: When not None, enables HTTP REST on the **same** TCP listener as
            WebSocket (unified ASGI). If both ``websocket_port`` and ``http_port`` are
            set, the WebSocket port is used for the shared listener.
        cors_origins: Optional CORS origins for WebSocket

    Returns:
        ``(agent_config, daemon_server_config)``
    """
    base_config = get_base_config()

    ws_p = websocket_port if websocket_port is not None else alloc_ephemeral_port()
    if http_port is not None:
        if websocket_port is not None:
            listen = websocket_port
        else:
            listen = http_port
        ws_p = listen

    daemon_config = {
        "transports": {
            "websocket": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": ws_p,
                "cors_origins": cors_origins or ["http://localhost:*", "http://127.0.0.1:*"],
            },
        },
    }

    if http_port is not None:
        daemon_config["transports"]["http_rest"] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": ws_p,
        }

    fs_middleware = base_config.filesystem_middleware.model_copy(
        update={"workspace_root": str(tmp_path / "workspace")}
    )
    agent = SootheConfig(
        providers=base_config.providers,
        router=base_config.router,
        vector_stores=base_config.vector_stores,
        vector_store_router=base_config.vector_store_router,
        filesystem_middleware=fs_middleware,
        persistence={"persist_dir": str(tmp_path / "persistence")},
        agent={
            "protocols": {
                "memory": {"enabled": False},
                "durability": {
                    "backend": "sqlite",
                    "persist_dir": str(tmp_path / "durability"),
                },
            },
            "autonomous": {"max_iterations": 3},
            "loop": {
                "limits": {
                    "max_parallel_goals": 1,
                    "max_parallel_steps": 1,
                    "global_max_llm_calls": 5,
                },
            },
        },
    )
    return agent, SootheDaemonConfig.model_validate(daemon_config)


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
