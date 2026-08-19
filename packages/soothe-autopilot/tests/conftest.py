"""Shared pytest configuration and fixtures for soothe-autopilot tests.

Re-exports the ``requires_llm_api`` fixture and ``--run-integration`` option
from the soothe package conftest so integration tests can use the same
skip-gate pattern without duplicating the probe logic.
"""

from __future__ import annotations

import os

import pytest


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


def _has_valid_api_key() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )


@pytest.fixture
def requires_llm_api():
    if not _has_valid_api_key():
        pytest.skip(
            "Test requires LLM API key (set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "DASHSCOPE_API_KEY, or DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL)"
        )
