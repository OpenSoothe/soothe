"""Conftest for daemon integration tests — exposes shared fixtures and hooks."""

from __future__ import annotations

from tests.integration.daemon_fixtures import (  # noqa: F401
    integration_config,
    llm_idle_timeout,
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    requires_llm_api,
    requires_postgresql,
    soothe_runner,
    temp_workspace,
    test_config,
    web_enabled_config,
)
