"""Shared test fixtures for soothe-community plugins."""

import pytest


@pytest.fixture
def mock_soothe_config():
    """Mock Soothe configuration for testing."""
    from unittest.mock import MagicMock

    config = MagicMock()
    config.subagents = {}
    return config
