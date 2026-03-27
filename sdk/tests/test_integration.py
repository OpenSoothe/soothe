"""Integration tests for plugin lifecycle."""

import pytest
from soothe_sdk import plugin, tool, subagent
from soothe_sdk.types import PluginContext


@pytest.mark.asyncio
async def test_plugin_lifecycle(mock_plugin_context):
    """Test plugin lifecycle hooks are called correctly."""

    load_called = False
    unload_called = False

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        async def on_load(self, context: PluginContext):
            nonlocal load_called
            load_called = True
            assert context is not None

        async def on_unload(self):
            nonlocal unload_called
            unload_called = True

        @tool(name="test-tool", description="Test tool")
        def test_tool(self, arg: str) -> str:
            return f"Result: {arg}"

    # Create plugin instance
    plugin_instance = TestPlugin()

    # Test on_load
    await plugin_instance.on_load(mock_plugin_context)
    assert load_called

    # Test on_unload
    await plugin_instance.on_unload()
    assert unload_called


@pytest.mark.asyncio
async def test_plugin_with_subagent(mock_plugin_context):
    """Test plugin with subagent creation."""

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        @subagent(name="test-agent", description="Test agent")
        async def create_agent(self, model, config, context):
            # Simulate creating a simple agent
            return {
                "name": "test-agent",
                "description": "Test agent",
                "runnable": None,  # Would be a CompiledSubAgent in real usage
            }

    # Create plugin instance
    plugin_instance = TestPlugin()

    # Create subagent
    result = await plugin_instance.create_agent(
        model=None, config={}, context=mock_plugin_context
    )

    assert result["name"] == "test-agent"
    assert result["description"] == "Test agent"


@pytest.mark.asyncio
async def test_plugin_health_check():
    """Test plugin health check."""

    @plugin(name="test-plugin", version="1.0.0", description="Test plugin")
    class TestPlugin:
        async def health_check(self):
            from soothe_sdk.types import PluginHealth

            return PluginHealth(status="healthy")

    # Create plugin instance
    plugin_instance = TestPlugin()

    # Check health
    health = await plugin_instance.health_check()
    assert health.status == "healthy"