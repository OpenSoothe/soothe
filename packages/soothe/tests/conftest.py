"""Shared pytest configuration and fixtures for soothe tests.

Layout:
  tests/unit/        — fast, isolated tests (default CI via verify_finally.sh)
  tests/integration/ — external services (Postgres, LLM APIs, network); skipped unless
                       ``pytest --run-integration`` or tests live only under unit/ with
                       ``@pytest.mark.integration``.

Skip rule: any test under ``tests/integration/`` or marked ``integration`` is skipped
when ``--run-integration`` is not passed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.runner import SootheRunner


def pytest_addoption(parser) -> None:
    """Add custom command-line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (tests/integration/ and @pytest.mark.integration)",
    )


def pytest_configure(config) -> None:
    """Register markers."""
    config.addinivalue_line("markers", "integration: requires external services or slow e2e")
    config.addinivalue_line("markers", "slow: long-running or stress tests")
    config.addinivalue_line("markers", "requires_postgresql: requires PostgreSQL database")
    config.addinivalue_line("markers", "requires_llm_api: requires LLM API keys")


def _is_integration_item(item: pytest.Item) -> bool:
    """True when the test should only run with ``--run-integration``."""
    if item.get_closest_marker("integration") is not None:
        return True
    path = str(item.path)
    return f"{os.sep}tests{os.sep}integration{os.sep}" in path


def pytest_collection_modifyitems(config, items) -> None:
    """Skip integration tests unless ``--run-integration`` is passed."""
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if _is_integration_item(item):
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# External service probes
# ---------------------------------------------------------------------------


def _has_postgresql() -> bool:
    return bool(
        os.getenv("POSTGRES_HOST")
        or os.getenv("PGHOST")
        or os.getenv("POSTGRES_URL")
        or os.getenv("DATABASE_URL")
    )


def _has_valid_api_key() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )


_CACHED_BASE_CONFIG: SootheConfig | None = None
_LAST_HOME_PATH: str | None = None


def get_base_config() -> SootheConfig:
    """Load integration base config once (develop config.yml or env override)."""
    global _CACHED_BASE_CONFIG
    if _CACHED_BASE_CONFIG is None:
        env_path = os.environ.get("SOOTHE_INTEGRATION_BASE_CONFIG", "").strip()
        if env_path:
            p = Path(env_path).expanduser()
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(p)) if p.is_file() else SootheConfig()
            )
        else:
            repo_root = Path(__file__).resolve().parents[3]
            config_path = repo_root / "config" / "develop" / "config.yml"
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(config_path))
                if config_path.is_file()
                else SootheConfig()
            )
    return _CACHED_BASE_CONFIG


def force_isolated_home(home: Path) -> None:
    """Point SOOTHE_HOME at a test-local directory."""
    global _LAST_HOME_PATH
    home_str = str(home)
    if _LAST_HOME_PATH == home_str:
        return
    _LAST_HOME_PATH = home_str
    os.environ["SOOTHE_HOME"] = home_str

    import soothe.config as soothe_config
    from soothe import config as config_module

    soothe_config.SOOTHE_HOME = home_str
    config_module.SOOTHE_HOME = home_str

    import soothe.runner._thread_manager as thread_manager

    thread_manager.SOOTHE_HOME = home_str


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    """Prevent LLM API key env leakage and rate-limit state across tests.

    Two problems solved:

    1. ``SootheConfig.propagate_env()`` uses ``os.environ.setdefault()``
       — a direct mutation that bypasses monkeypatch and persists for
       the session.  When a test sets a fake ``OPENAI_API_KEY`` this way,
       later tests that call ``config.create_chat_model()`` attempt real
       network calls, blocking for minutes on timeouts.

    2. ``LLMRateLimitRegistry`` is a process-wide singleton whose
       ``ThreadBudget.request_times`` accumulates across tests.  After 60
       mock LLM calls within 60s, ``wait_for_rpm_slot()`` blocks for up
       to 60s, causing tests to appear to hang.
    """
    _llm_env_vars = (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ADMIN_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_CP_API_KEY",
        "DASHSCOPE_CP_BASE_URL",
        "OLLAMA_HOST",
    )
    saved = {k: os.environ.get(k) for k in _llm_env_vars}

    # Reset the LLM rate-limit registry singleton so ThreadBudget state
    # from prior tests (request_times, semaphores) doesn't leak forward.
    try:
        from soothe.middleware.llm_rate_limit import LLMRateLimitRegistry

        LLMRateLimitRegistry.reset_for_tests()
    except Exception:
        pass

    yield

    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


@pytest.fixture
def requires_postgresql():
    if not _has_postgresql():
        pytest.skip(
            "Test requires PostgreSQL (set POSTGRES_HOST, POSTGRES_URL, PGHOST, or DATABASE_URL)"
        )


@pytest.fixture
def requires_llm_api():
    if not _has_valid_api_key():
        pytest.skip(
            "Test requires LLM API key (set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "or DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL)"
        )


@pytest.fixture
def test_config() -> SootheConfig:
    return get_base_config().model_copy(deep=True)


@pytest.fixture
def integration_config(test_config: SootheConfig) -> SootheConfig:
    test_config.agent.loop.concurrency.max_parallel_goals = 1
    test_config.agent.loop.concurrency.max_parallel_steps = 1
    test_config.agent.loop.concurrency.global_max_llm_calls = 3
    test_config.agent.autopilot.max_iterations = 5
    if os.getenv("ANTHROPIC_API_KEY") and not (
        os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL")
    ):
        test_config.router.default = "anthropic:claude-sonnet-4-5"
        test_config.router.fast = "anthropic:claude-haiku-3-5"
        test_config.agent.protocols.memory.enabled = False
    return test_config


@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    if not _has_valid_api_key():
        pytest.skip(
            "Integration tests require OPENAI_API_KEY, ANTHROPIC_API_KEY, or Dashscope credentials"
        )
    runner = SootheRunner(integration_config)
    yield runner
    if hasattr(runner, "cleanup"):
        await runner.cleanup()


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def web_enabled_config(test_config: SootheConfig) -> SootheConfig:
    from soothe.config.models import ToolsConfig

    test_config.tools = ToolsConfig(
        execution={"enabled": True},
        file_ops={"enabled": True},
        code_edit={"enabled": True},
        web_search={"enabled": True},
    )
    return test_config
