"""Conftest for daemon integration tests — exposes shared fixtures and hooks."""

from __future__ import annotations

from tests.integration.daemon_fixtures import (  # noqa: F401
    llm_idle_timeout,
    requires_llm_api,
    requires_postgresql,
    soothe_runner,
    integration_config,
    test_config,
    temp_workspace,
    web_enabled_config,
    pytest_addoption,
    pytest_configure,
    pytest_collection_modifyitems,
)
