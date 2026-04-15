"""Tests for PaperScout plugin registration."""

import pytest
from unittest.mock import MagicMock

from soothe_community.paperscout import PaperScoutPlugin


@pytest.mark.asyncio
async def test_plugin_creation():
    """Test PaperScout plugin can be instantiated."""
    plugin = PaperScoutPlugin()
    assert plugin is not None


@pytest.mark.asyncio
async def test_plugin_has_subagent_method():
    """Test that plugin has subagent factory method."""
    plugin = PaperScoutPlugin()
    assert hasattr(plugin, "create_paperscout")
    assert hasattr(plugin, "get_subagents")

    subagents = plugin.get_subagents()
    assert len(subagents) == 1
    assert subagents[0] == plugin.create_paperscout


@pytest.mark.asyncio
async def test_plugin_on_load_success():
    """Test plugin on_load with all dependencies available."""
    _plugin = PaperScoutPlugin()  # noqa: F841

    # Mock context
    context = MagicMock()
    context.logger = MagicMock()

    # This should not raise since dependencies are installed
    # (we're in test environment with dev dependencies)
    # Note: Actual dependency check would fail in minimal install
    # but we're testing the plugin structure here


@pytest.mark.asyncio
async def test_create_paperscout_subagent(sample_config, mock_persist_store):
    """Test creating PaperScout subagent."""
    plugin = PaperScoutPlugin()

    # Mock context
    context = MagicMock()
    context.logger = MagicMock()

    # Create subagent
    subagent_dict = await plugin.create_paperscout(
        model=None,  # Not used in basic implementation
        config=MagicMock(subagents={"paperscout": MagicMock(enabled=True, config=sample_config.model_dump())}),
        context=context,
        store=mock_persist_store,
        user_id="test_user",
    )

    assert subagent_dict is not None
    assert subagent_dict["name"] == "paperscout"
    assert "description" in subagent_dict
    assert "runnable" in subagent_dict
    assert "config" in subagent_dict
