"""Configuration and fixtures for integration tests."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from soothe.config import SootheConfig
from soothe.runner import SootheRunner

from soothe_daemon.config import SootheDaemonConfig
from tests.integration.test_timeouts import integration_llm_idle_timeout


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
    subscribe_timeout_s: float | None = None,
) -> str:
    """Create or attach to a loop and subscribe for streaming; returns ``loop_id``.

    Args:
        client: Connected ``WebSocketClient``.
        resume_loop_id: If set, reattach to this loop instead of creating new.
        subscribe_timeout_s: Override for ``loop_new`` / ``loop_reattach`` /
            ``loop_events`` RPC timeouts. Defaults to
            :func:`integration_llm_idle_timeout` so the daemon has adequate time
            to respond even when it is processing an LLM turn concurrently.
    """
    from soothe_client.session import bootstrap_loop_session

    if subscribe_timeout_s is None:
        subscribe_timeout_s = integration_llm_idle_timeout()

    ev = await bootstrap_loop_session(
        client,
        resume_loop_id=resume_loop_id,
        subscribe_timeout_s=subscribe_timeout_s,
    )
    if ev.get("type") == "error" or not ev.get("success", True):
        raise RuntimeError(str(ev.get("message", "loop bootstrap failed")))
    lid = ev.get("loop_id")
    if not lid:
        raise RuntimeError("bootstrap missing loop_id")
    return str(lid)


async def websocket_create_loop_only(client: Any, *, timeout: float = 10.0) -> str:
    """Allocate a new ``loop_id`` without ``loop_subscribe`` (unsubscribed client tests)."""
    await client.request_connection_init()
    await client.wait_for_connection_ack(ack_timeout_s=timeout)
    resp = await client.request("loop_new", {}, timeout=timeout)
    lid = str(resp.get("loop_id") or "").strip()
    if not lid:
        raise RuntimeError("loop_new response missing loop_id")
    return lid


# Cache for base config to avoid repeated file reads
_CACHED_BASE_CONFIG: SootheConfig | None = None

# Track last home path to avoid unnecessary module reloads
_LAST_HOME_PATH: str | None = None


# Host `soothed` default WebSocket port — integration tests must never bind it.
PRODUCTION_DAEMON_WS_PORT = 8765


def alloc_ephemeral_port(
    *,
    exclude: frozenset[int] | None = None,
) -> int:
    """Allocate an available localhost TCP port for testing.

    Never returns the live-daemon production port (``8765``) so parallel
    ``pytest --run-integration`` cannot steal or collide with a running
    ``soothed`` on the host.
    """
    blocked = exclude if exclude is not None else frozenset({PRODUCTION_DAEMON_WS_PORT})
    for _ in range(32):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = int(s.getsockname()[1])
        if port not in blocked:
            return port
    msg = f"Could not allocate a TCP port outside {sorted(blocked)}"
    raise RuntimeError(msg)


def get_base_config() -> SootheConfig:
    """Get base config, loading from file once and caching the result.

    Resolution order:
        1. ``SOOTHE_INTEGRATION_BASE_CONFIG`` — explicit path to a custom YAML file.
        2. Repo ``config/develop/nano.yml`` (monorepo root = parents[4] of this file).
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
            config_path = repo_root / "config" / "develop" / "nano.yml"
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(config_path))
                if config_path.is_file()
                else SootheConfig()
            )
    return _CACHED_BASE_CONFIG


def force_isolated_home(home: Path) -> None:
    """Force daemon paths to a test-local SOOTHE_HOME.

    Updates the ``SOOTHE_HOME`` module attribute on each path module directly
    (no ``importlib.reload`` — that leaks file descriptors under the macOS
    default FD limit). Skips the assignment if ``home`` matches the last
    applied path.
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

    import soothe.runner._thread_manager as thread_manager

    thread_manager.SOOTHE_HOME = Path(home_str)

    import soothe_sdk.paths as sdk_config

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
    cors_origins: list[str] | None = None,
) -> tuple[SootheConfig, SootheDaemonConfig]:
    """Build isolated agent and daemon server configs (RFC-450).

    ``SootheConfig`` intentionally omits a ``daemon:`` block (it is stripped at
    validation). Pass the returned :class:`SootheDaemonConfig` as
    ``SootheDaemon(..., daemon_config=...)``.

    Args:
        tmp_path: Temporary path for test isolation
        websocket_port: WebSocket port (primary transport for bidirectional streaming)
        cors_origins: Optional CORS origins for WebSocket

    Returns:
        ``(agent_config, daemon_server_config)``
    """
    base_config = get_base_config()

    if websocket_port == PRODUCTION_DAEMON_WS_PORT:
        msg = (
            f"Integration tests must not bind production daemon port "
            f"{PRODUCTION_DAEMON_WS_PORT}; pass None or alloc_ephemeral_port()"
        )
        raise ValueError(msg)

    ws_p = websocket_port if websocket_port is not None else alloc_ephemeral_port()

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

    fs_middleware = base_config.filesystem_middleware.model_copy(
        update={"workspace_root": str(tmp_path / "workspace")}
    )
    agent = SootheConfig(
        providers=base_config.providers,
        router_profiles=base_config.router_profiles,
        active_router_profile=base_config.active_router_profile,
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
            "autopilot": {"max_iterations": 3},
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
        if event is None:
            continue
        # Protocol-1 wraps legacy streaming frames (status/event/card.*/…)
        # in ``next`` envelopes; unwrap to the inner ``data`` so callers can
        # match on the originating frame ``type``. Pure protocol-1 frames
        # (error/response/complete) pass through unchanged.
        frame = unwrap_next(event)
        if isinstance(frame, dict) and frame.get("type") == expected_type:
            return frame


def unwrap_next(event: dict | None) -> dict | None:
    """Unwrap a protocol-1 ``next`` envelope to its ``payload.data`` frame.

    Under protocol-1 (RFC-450 §9.3) the daemon wraps every legacy streaming
    frame (status/event/command_response/subscription ack) in a
    ``{proto, type:"next", payload:{namespace, mode, data}}`` envelope. This
    helper returns the inner ``data`` dict (the original frame) so tests can
    branch on the legacy ``type``/``state``/``loop_id`` fields as before.
    Non-``next`` frames (response/error/complete/etc.) are returned unchanged.

    Args:
        event: A raw wire frame as returned by ``client.read_event()``.

    Returns:
        The inner ``payload.data`` dict for ``next`` envelopes, the original
        frame otherwise, or ``None`` if ``event`` is ``None``.
    """
    if not isinstance(event, dict):
        return event
    if event.get("type") != "next":
        return event
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return event
    data = payload.get("data")
    return data if isinstance(data, dict) else event


async def await_next_mode(
    readable,
    expected_mode: str | set[str] | tuple[str, ...],
    timeout: float = 5.0,
) -> dict:
    """Read until a protocol-1 ``next`` envelope with the expected ``mode`` arrives.

    ``mode`` is the originating legacy frame type (``status``/``event``/
    ``command_response``/...), carried on ``payload.mode``. Returns the inner
    ``payload.data`` frame (see :func:`unwrap_next`).

    Args:
        readable: Async callable returning the next wire frame.
        expected_mode: Mode string or set of strings to wait for.
        timeout: Maximum wait time in seconds.

    Returns:
        The inner ``data`` dict of the matching ``next`` envelope.

    Raises:
        TimeoutError: If no matching frame arrives in time.
    """
    modes = {expected_mode} if isinstance(expected_mode, str) else set(expected_mode)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Timed out waiting for next mode: {', '.join(sorted(modes))}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is None:
            continue
        if event.get("type") != "next":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("mode") in modes:
            data = payload.get("data")
            return data if isinstance(data, dict) else {}


async def await_subscribe_ack(
    readable,
    loop_id: str,
    *,
    timeout: float = 5.0,
) -> dict:
    """Wait for the protocol-1 subscribe-ack ``next`` envelope for ``loop_id``.

    Under protocol-1 (RFC-450 §9.3) the daemon confirms a ``loop_events``
    subscription with a ``next`` envelope whose ``payload.event == "subscribed"``
    and ``payload.loop_id`` matches. Returns the ``payload`` dict.

    Args:
        readable: Async callable returning the next wire frame.
        loop_id: Loop id the subscribe-ack must reference.
        timeout: Maximum wait time in seconds.

    Returns:
        The subscribe-ack ``payload`` dict.

    Raises:
        TimeoutError: If no matching ack arrives in time.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Timed out waiting for subscribe-ack for loop {loop_id!r}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is None:
            continue
        if event.get("type") != "next":
            continue
        payload = event.get("payload")
        if (
            isinstance(payload, dict)
            and payload.get("event") == "subscribed"
            and str(payload.get("loop_id") or "") == str(loop_id)
        ):
            return payload


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
        # Under protocol-1 (RFC-450 §9.3) status frames arrive wrapped in a
        # ``next`` envelope; unwrap to the inner ``data`` so callers see the
        # legacy ``{type:"status", state, loop_id}`` shape.
        frame = unwrap_next(event)
        if (
            isinstance(frame, dict)
            and frame.get("type") == "status"
            and frame.get("state") in expected
        ):
            return frame


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
        test_config: Base config loaded from config/develop/nano.yml

    Returns:
        SootheConfig with test-specific overrides
    """
    # Use smaller limits for faster testing
    test_config.agent.loop.concurrency.max_parallel_goals = 1
    test_config.agent.loop.concurrency.max_parallel_steps = 1
    test_config.agent.loop.concurrency.global_max_llm_calls = 3
    test_config.agent.autopilot.max_iterations = 5

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
        test_config: Base config loaded from config/develop/nano.yml

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


# ---------------------------------------------------------------------------
# Safe Daemon / Client Lifecycle Helpers
# ---------------------------------------------------------------------------

_DAEMON_STOP_TIMEOUT_S = 8.0
_CLIENT_CLOSE_TIMEOUT_S = 3.0
_SUBPROCESS_KILL_TIMEOUT_S = 5.0


async def stop_daemon_safely(
    daemon: Any,
    *,
    timeout: float = _DAEMON_STOP_TIMEOUT_S,
) -> None:
    """Stop ``daemon`` with a hard timeout.

    ``daemon.stop()`` can hang indefinitely when psycopg pool worker threads
    are blocked on dead sockets (macOS ``kevent``).  This wraps the call in
    ``asyncio.wait_for`` so the test suite is not blocked.

    Does NOT cancel pending tasks on the event loop — doing so would shut
    down shared ThreadPoolExecutors and cause ``cannot schedule new futures
    after shutdown`` in subsequent tests under a session-scoped loop.
    """
    if daemon is None:
        return
    try:
        await asyncio.wait_for(daemon.stop(), timeout=timeout)
    except (TimeoutError, Exception):
        pass


async def close_client_safely(
    client: Any,
    *,
    timeout: float = _CLIENT_CLOSE_TIMEOUT_S,
) -> None:
    """Close ``WebSocketClient`` with a timeout, suppressing errors.

    If the daemon has already been stopped the underlying socket may be dead;
    ``client.close()`` would hang or raise.  This bounds the close and
    suppresses so ``finally`` blocks never mask the real test failure.
    """
    if client is None:
        return
    try:
        await asyncio.wait_for(client.close(), timeout=timeout)
    except (TimeoutError, Exception):
        pass


def stop_subprocess_daemon(
    proc: subprocess.Popen | None,
    *,
    timeout: float = _SUBPROCESS_KILL_TIMEOUT_S,
) -> None:
    """Terminate a subprocess daemon: ``terminate → wait → kill → wait``.

    Also closes ``stdout`` / ``stderr`` pipes and kills the whole process
    group (``os.killpg``) when the subprocess was started with
    ``start_new_session=True``.
    """
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except Exception:
        try:
            # Process-group kill (only if started with start_new_session=True)
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
