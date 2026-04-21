"""Tests for the Soothe SDK."""

import pytest

from soothe_sdk.plugin import (
    Health as PluginHealth,
)
from soothe_sdk.plugin import (
    Manifest as PluginManifest,
)
from soothe_sdk.plugin import (
    plugin,
    subagent,
    tool,
    tool_group,
)


def test_plugin_decorator():
    """Test @plugin decorator creates manifest correctly."""

    @plugin(
        name="test-plugin",
        version="1.0.0",
        description="Test plugin",
        dependencies=["langchain>=0.1.0"],
    )
    class TestPlugin:
        pass

    instance = TestPlugin()

    # Check manifest exists
    assert hasattr(instance, "manifest")
    assert isinstance(instance.manifest, PluginManifest)

    # Check manifest fields
    assert instance.manifest.name == "test-plugin"
    assert instance.manifest.version == "1.0.0"
    assert instance.manifest.description == "Test plugin"
    assert instance.manifest.dependencies == ["langchain>=0.1.0"]


def test_tool_decorator():
    """Test @tool decorator marks methods correctly."""

    @plugin(name="test", version="1.0.0", description="Test")
    class TestPlugin:
        @tool(name="greet", description="Greet someone")
        def greet(self, name: str) -> str:
            return f"Hello, {name}!"

    instance = TestPlugin()

    # Check tool metadata
    assert hasattr(instance.greet, "_is_tool")
    assert instance.greet._tool_name == "greet"
    assert instance.greet._tool_description == "Greet someone"

    # Check tool works
    result = instance.greet("World")
    assert result == "Hello, World!"

    # Check get_tools() method
    tools = instance.get_tools()
    assert len(tools) == 1
    assert tools[0]._tool_name == "greet"


def test_tool_group_decorator():
    """Test @tool_group decorator organizes tools."""

    @plugin(name="test", version="1.0.0", description="Test")
    class TestPlugin:
        @tool_group(name="math", description="Math tools")
        class MathTools:
            @tool(name="add", description="Add numbers")
            def add(self, a: int, b: int) -> int:
                return a + b

            @tool(name="multiply", description="Multiply numbers")
            def multiply(self, a: int, b: int) -> int:
                return a * b

    instance = TestPlugin()
    math = instance.MathTools()

    # Check tool group metadata
    assert hasattr(instance.MathTools, "_is_tool_group")
    assert instance.MathTools._tool_group_name == "math"

    # Check tools work
    assert math.add(2, 3) == 5
    assert math.multiply(2, 3) == 6


def test_subagent_decorator():
    """Test @subagent decorator marks factory methods."""

    @plugin(name="test", version="1.0.0", description="Test")
    class TestPlugin:
        @subagent(
            name="researcher",
            description="Research subagent",
            model="openai:gpt-4o-mini",
        )
        async def create_researcher(self, model, config, context):
            return {
                "name": "researcher",
                "description": "Research subagent",
                "runnable": None,
            }

    instance = TestPlugin()

    # Check subagent metadata
    assert hasattr(instance.create_researcher, "_is_subagent")
    assert instance.create_researcher._subagent_name == "researcher"
    assert instance.create_researcher._subagent_description == "Research subagent"
    assert instance.create_researcher._subagent_model == "openai:gpt-4o-mini"

    # Check get_subagents() method
    subagents = instance.get_subagents()
    assert len(subagents) == 1
    assert subagents[0]._subagent_name == "researcher"


def test_plugin_manifest_validation():
    """Test PluginManifest validation."""
    # Valid manifest
    manifest = PluginManifest(
        name="test",
        version="1.0.0",
        description="Test",
    )
    assert manifest.name == "test"
    assert manifest.trust_level == "standard"  # Default

    # Test defaults
    assert manifest.dependencies == []
    assert manifest.python_version == ">=3.11"
    assert manifest.soothe_version == ">=0.1.0"


def test_plugin_health():
    """Test PluginHealth model."""
    health = PluginHealth(status="healthy", message="All good")
    assert health.status == "healthy"
    assert health.message == "All good"
    assert health.details == {}


def test_multiple_tools():
    """Test plugin with multiple tools."""

    @plugin(name="test", version="1.0.0", description="Test")
    class MultiToolPlugin:
        @tool(name="tool1", description="First tool")
        def tool1(self, x: int) -> int:
            return x * 2

        @tool(name="tool2", description="Second tool")
        def tool2(self, x: int) -> int:
            return x * 3

        @tool(name="tool3", description="Third tool")
        def tool3(self, x: int) -> int:
            return x * 4

    instance = MultiToolPlugin()
    tools = instance.get_tools()

    assert len(tools) == 3
    assert instance.tool1(5) == 10
    assert instance.tool2(5) == 15
    assert instance.tool3(5) == 20


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
