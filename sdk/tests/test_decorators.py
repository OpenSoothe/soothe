"""Tests for decorator functionality."""

import pytest
from soothe_sdk import plugin, tool, subagent, PluginError


def test_plugin_decorator():
    """Test plugin decorator sets metadata correctly."""

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        pass

    assert hasattr(TestPlugin, "_plugin_metadata")
    metadata = TestPlugin._plugin_metadata
    assert metadata["name"] == "test-plugin"
    assert metadata["version"] == "1.0.0"
    assert metadata["description"] == "Test plugin"


def test_tool_decorator():
    """Test tool decorator sets metadata correctly."""

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        @tool(name="test-tool", description="Test tool")
        def test_tool(self, arg: str) -> str:
            return f"Result: {arg}"

    # Check tool metadata
    assert hasattr(TestPlugin.test_tool, "_tool_metadata")
    metadata = TestPlugin.test_tool._tool_metadata
    assert metadata["name"] == "test-tool"
    assert metadata["description"] == "Test tool"


@pytest.mark.asyncio
async def test_subagent_decorator():
    """Test subagent decorator sets metadata correctly."""

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        @subagent(name="test-agent", description="Test agent")
        async def create_agent(self, model, config, context):
            return {
                "name": "test-agent",
                "description": "Test agent",
                "runnable": None,
            }

    # Check subagent metadata
    assert hasattr(TestPlugin.create_agent, "_subagent_metadata")
    metadata = TestPlugin.create_agent._subagent_metadata
    assert metadata["name"] == "test-agent"
    assert metadata["description"] == "Test agent"


def test_plugin_missing_name():
    """Test plugin decorator raises error when name is missing."""
    with pytest.raises(PluginError):

        @plugin(version="1.0.0", description="Test plugin")
        class TestPlugin:
            pass


def test_plugin_missing_version():
    """Test plugin decorator raises error when version is missing."""
    with pytest.raises(PluginError):

        @plugin(name="test-plugin", description="Test plugin")
        class TestPlugin:
            pass


def test_plugin_missing_description():
    """Test plugin decorator raises error when description is missing."""
    with pytest.raises(PluginError):

        @plugin(name="test-plugin", version="1.0.0")
        class TestPlugin:
            pass