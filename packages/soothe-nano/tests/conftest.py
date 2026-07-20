"""Pytest fixtures for soothe-nano (no SootheRunner / StrangeLoop)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from soothe_nano.config import SootheConfig


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


@pytest.fixture
def test_config() -> SootheConfig:
    """Minimal NanoConfig for unit tests."""
    return SootheConfig()


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Isolated workspace directory for filesystem/tool tests."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def _isolate_soothe_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point SOOTHE_HOME at a temp dir that does not pollute per-test tmp_path."""
    home = tmp_path_factory.mktemp("soothe-home")
    monkeypatch.setenv("SOOTHE_HOME", str(home))
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe_nano.config.env.SOOTHE_HOME", home)
