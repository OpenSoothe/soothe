"""Test configuration for soothe-sdk tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_soothe_config():
    """Create mock Soothe configuration."""
    config = MagicMock()
    config.resolve_model = MagicMock(return_value="openai:gpt-4o-mini")
    config.create_chat_model = MagicMock()
    return config


@pytest.fixture
def mock_plugin_context(mock_soothe_config):
    """Create mock plugin context."""
    context = MagicMock()
    context.config = {}
    context.soothe_config = mock_soothe_config
    context.logger = MagicMock()
    context.emit_event = MagicMock()
    return context
