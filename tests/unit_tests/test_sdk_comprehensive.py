"""Comprehensive unit tests for the Soothe SDK.

This test module covers:
- @plugin decorator with all configuration options
- @tool decorator with sync/async functions
- @tool_group decorator with nested classes
- @subagent decorator with factory methods
- PluginManifest validation and edge cases
- PluginContext and SootheConfigProtocol
- PluginHealth model
- Exception hierarchy
- Error handling and validation
- Integration scenarios
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_sdk import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
    plugin,
    subagent,
    tool,
    tool_group,
)
from soothe_sdk.types import PluginContext, PluginHealth, PluginManifest
from soothe_sdk.types.context import SootheConfigProtocol


class TestPluginDecorator:
    """Test @plugin decorator functionality."""

    def test_minimal_plugin(self):
        """Test plugin with minimal required fields."""

        @plugin(name="test", version="1.0.0", description="Test plugin")
        class MinimalPlugin:
            pass

        instance = MinimalPlugin()
        assert hasattr(instance, "manifest")
        assert instance.manifest.name == "test"
        assert instance.manifest.version == "1.0.0"
        assert instance.manifest.description == "Test plugin"

    def test_full_plugin_metadata(self):
        """Test plugin with all metadata fields."""

        @plugin(
            name="advanced-plugin",
            version="2.1.0",
            description="Advanced plugin with all metadata",
            author="Test Author",
            homepage="https://example.com/plugin",
            repository="https://github.com/example/plugin",
            license="Apache-2.0",
            dependencies=["langchain>=0.1.0", "pydantic>=2.0.0"],
            python_version=">=3.11",
            soothe_version=">=0.2.0",
            trust_level="trusted",
        )
        class AdvancedPlugin:
            pass

        instance = AdvancedPlugin()
        manifest = instance.manifest

        assert manifest.name == "advanced-plugin"
        assert manifest.version == "2.1.0"
        assert manifest.description == "Advanced plugin with all metadata"
        assert manifest.author == "Test Author"
        assert manifest.homepage == "https://example.com/plugin"
        assert manifest.repository == "https://github.com/example/plugin"
        assert manifest.license == "Apache-2.0"
        assert manifest.dependencies == ["langchain>=0.1.0", "pydantic>=2.0.0"]
        assert manifest.python_version == ">=3.11"
        assert manifest.soothe_version == ">=0.2.0"
        assert manifest.trust_level == "trusted"

    def test_trust_levels(self):
        """Test all valid trust levels."""
        for level in ["built-in", "trusted", "standard", "untrusted"]:

            @plugin(name="test", version="1.0.0", description="Test", trust_level=level)
            class TrustPlugin:
                pass

            instance = TrustPlugin()
            assert instance.manifest.trust_level == level

    def test_get_tools_empty(self):
        """Test get_tools() with no tools."""

        @plugin(name="test", version="1.0.0", description="Test")
        class NoToolsPlugin:
            pass

        instance = NoToolsPlugin()
        tools = instance.get_tools()
        assert tools == []

    def test_get_subagents_empty(self):
        """Test get_subagents() with no subagents."""

        @plugin(name="test", version="1.0.0", description="Test")
        class NoSubagentsPlugin:
            pass

        instance = NoSubagentsPlugin()
        subagents = instance.get_subagents()
        assert subagents == []

    def test_manifest_timestamps(self):
        """Test manifest has valid timestamps."""

        @plugin(name="test", version="1.0.0", description="Test")
        class TimestampPlugin:
            pass

        instance = TimestampPlugin()
        assert isinstance(instance.manifest.created_at, datetime)
        assert isinstance(instance.manifest.updated_at, datetime)
        # Ensure timestamps are recent
        now = datetime.now(UTC)
        assert (now - instance.manifest.created_at).total_seconds() < 5

    def test_plugin_inheritance(self):
        """Test plugin class can be inherited."""

        @plugin(name="base", version="1.0.0", description="Base")
        class BasePlugin:
            @tool(name="base_tool", description="Base tool")
            def base_method(self):
                return "base"

        class DerivedPlugin(BasePlugin):
            @tool(name="derived_tool", description="Derived tool")
            def derived_method(self):
                return "derived"

        instance = DerivedPlugin()
        tools = instance.get_tools()
        # Should have both base and derived tools
        assert len(tools) == 2


class TestToolDecorator:
    """Test @tool decorator functionality."""

    def test_sync_tool(self):
        """Test synchronous tool."""

        @plugin(name="test", version="1.0.0", description="Test")
        class SyncPlugin:
            @tool(name="add", description="Add two numbers")
            def add(self, a: int, b: int) -> int:
                return a + b

        instance = SyncPlugin()
        result = instance.add(2, 3)
        assert result == 5

        # Check metadata
        assert hasattr(instance.add, "_is_tool")
        assert instance.add._tool_name == "add"
        assert instance.add._tool_description == "Add two numbers"

    @pytest.mark.asyncio
    async def test_async_tool(self):
        """Test asynchronous tool."""

        @plugin(name="test", version="1.0.0", description="Test")
        class AsyncPlugin:
            @tool(name="async_op", description="Async operation")
            async def async_operation(self, value: int) -> int:
                await asyncio.sleep(0.01)
                return value * 2

        instance = AsyncPlugin()
        result = await instance.async_operation(5)
        assert result == 10

        # Check metadata
        assert hasattr(instance.async_operation, "_is_tool")

    def test_tool_with_group(self):
        """Test tool with group assignment."""

        @plugin(name="test", version="1.0.0", description="Test")
        class GroupedPlugin:
            @tool(name="tool1", description="Tool 1", group="math")
            def method1(self):
                pass

            @tool(name="tool2", description="Tool 2", group="math")
            def method2(self):
                pass

        instance = GroupedPlugin()
        tools = instance.get_tools()

        assert len(tools) == 2
        assert all(t._tool_group == "math" for t in tools)

    def test_multiple_tools(self):
        """Test multiple tools in single plugin."""

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

            def regular_method(self):
                """Not a tool."""
                return "not a tool"

        instance = MultiToolPlugin()
        tools = instance.get_tools()

        assert len(tools) == 3
        assert instance.tool1(5) == 10
        assert instance.tool2(5) == 15
        assert instance.tool3(5) == 20
        assert instance.regular_method() == "not a tool"

    def test_tool_with_complex_types(self):
        """Test tool with complex parameter types."""

        @plugin(name="test", version="1.0.0", description="Test")
        class ComplexPlugin:
            @tool(name="process", description="Process data")
            def process(
                self,
                items: list[str],
                config: dict[str, Any],
                optional_val: int | None = None,
            ) -> dict[str, Any]:
                return {
                    "items": items,
                    "config": config,
                    "optional": optional_val,
                }

        instance = ComplexPlugin()
        result = instance.process(
            items=["a", "b"],
            config={"key": "value"},
            optional_val=42,
        )

        assert result["items"] == ["a", "b"]
        assert result["config"] == {"key": "value"}
        assert result["optional"] == 42

    def test_tool_preserves_function_metadata(self):
        """Test that tool decorator preserves function metadata."""

        @plugin(name="test", version="1.0.0", description="Test")
        class MetaPlugin:
            @tool(name="documented", description="Documented tool")
            def documented_tool(self, value: int) -> int:
                """This is a well-documented tool."""
                return value

        instance = MetaPlugin()
        # The wrapper should preserve docstring
        assert "well-documented" in instance.documented_tool.__doc__


class TestToolGroupDecorator:
    """Test @tool_group decorator functionality."""

    def test_tool_group_basic(self):
        """Test basic tool group."""

        @plugin(name="test", version="1.0.0", description="Test")
        class PluginWithGroup:
            @tool_group(name="math", description="Math operations")
            class MathTools:
                @tool(name="add", description="Add numbers")
                def add(self, a: int, b: int) -> int:
                    return a + b

                @tool(name="multiply", description="Multiply numbers")
                def multiply(self, a: int, b: int) -> int:
                    return a * b

        instance = PluginWithGroup()
        math = instance.MathTools()

        # Check group metadata
        assert hasattr(instance.MathTools, "_is_tool_group")
        assert instance.MathTools._tool_group_name == "math"
        assert instance.MathTools._tool_group_description == "Math operations"

        # Check tools work
        assert math.add(2, 3) == 5
        assert math.multiply(2, 3) == 6

    def test_tool_group_get_tools(self):
        """Test get_tools() method on tool group."""

        @plugin(name="test", version="1.0.0", description="Test")
        class PluginWithGroup:
            @tool_group(name="utils", description="Utility tools")
            class Utils:
                @tool(name="tool1", description="Tool 1")
                def tool1(self):
                    return 1

                @tool(name="tool2", description="Tool 2")
                def tool2(self):
                    return 2

        instance = PluginWithGroup()
        utils = instance.Utils()
        tools = utils.get_tools()

        assert len(tools) == 2

    def test_nested_tool_groups(self):
        """Test multiple nested tool groups."""

        @plugin(name="test", version="1.0.0", description="Test")
        class MultiGroupPlugin:
            @tool_group(name="math", description="Math tools")
            class MathTools:
                @tool(name="add", description="Add")
                def add(self, a, b):
                    return a + b

            @tool_group(name="string", description="String tools")
            class StringTools:
                @tool(name="upper", description="Uppercase")
                def upper(self, s):
                    return s.upper()

        instance = MultiGroupPlugin()
        math = instance.MathTools()
        string = instance.StringTools()

        assert math.add(1, 2) == 3
        assert string.upper("hello") == "HELLO"

    def test_tool_group_with_regular_methods(self):
        """Test tool group with mix of tools and regular methods."""

        @plugin(name="test", version="1.0.0", description="Test")
        class MixedPlugin:
            @tool_group(name="mixed", description="Mixed methods")
            class MixedTools:
                @tool(name="tool", description="A tool")
                def tool_method(self):
                    return "tool"

                def regular_method(self):
                    """Not a tool."""
                    return "regular"

        instance = MixedPlugin()
        mixed = instance.MixedTools()
        tools = mixed.get_tools()

        assert len(tools) == 1
        assert tools[0]._tool_name == "tool"


class TestSubagentDecorator:
    """Test @subagent decorator functionality."""

    @pytest.mark.asyncio
    async def test_subagent_basic(self):
        """Test basic subagent factory."""

        @plugin(name="test", version="1.0.0", description="Test")
        class SubagentPlugin:
            @subagent(
                name="researcher",
                description="Research subagent",
                model="openai:gpt-4o-mini",
            )
            async def create_researcher(self, model, config, context):
                return {
                    "name": "researcher",
                    "description": "Research subagent",
                    "runnable": MagicMock(),
                }

        instance = SubagentPlugin()

        # Check metadata
        assert hasattr(instance.create_researcher, "_is_subagent")
        assert instance.create_researcher._subagent_name == "researcher"
        assert instance.create_researcher._subagent_description == "Research subagent"
        assert instance.create_researcher._subagent_model == "openai:gpt-4o-mini"

        # Test calling the factory
        mock_model = MagicMock()
        mock_config = MagicMock()
        mock_context = MagicMock()

        result = await instance.create_researcher(mock_model, mock_config, mock_context)
        assert result["name"] == "researcher"

    @pytest.mark.asyncio
    async def test_subagent_with_kwargs(self):
        """Test subagent factory with additional kwargs."""

        @plugin(name="test", version="1.0.0", description="Test")
        class ConfigurablePlugin:
            @subagent(name="custom", description="Custom subagent")
            async def create_custom(self, model, config, context, **kwargs):
                return {
                    "name": "custom",
                    "custom_config": kwargs.get("custom_config", {}),
                }

        instance = ConfigurablePlugin()
        result = await instance.create_custom(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            custom_config={"setting": "value"},
        )

        assert result["custom_config"] == {"setting": "value"}

    @pytest.mark.asyncio
    async def test_multiple_subagents(self):
        """Test plugin with multiple subagents."""

        @plugin(name="test", version="1.0.0", description="Test")
        class MultiSubagentPlugin:
            @subagent(name="agent1", description="First agent")
            async def create_agent1(self, model, config, context):
                return {"name": "agent1"}

            @subagent(name="agent2", description="Second agent")
            async def create_agent2(self, model, config, context):
                return {"name": "agent2"}

        instance = MultiSubagentPlugin()
        subagents = instance.get_subagents()

        assert len(subagents) == 2
        assert subagents[0]._subagent_name == "agent1"
        assert subagents[1]._subagent_name == "agent2"

    def test_subagent_without_model(self):
        """Test subagent without default model."""

        @plugin(name="test", version="1.0.0", description="Test")
        class NoModelPlugin:
            @subagent(name="flexible", description="Flexible subagent")
            async def create_flexible(self, model, config, context):
                return {"name": "flexible"}

        instance = NoModelPlugin()
        assert instance.create_flexible._subagent_model is None


class TestPluginManifest:
    """Test PluginManifest model."""

    def test_minimal_manifest(self):
        """Test manifest with minimal required fields."""
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            description="Test plugin",
        )

        assert manifest.name == "test-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.description == "Test plugin"
        assert manifest.author == ""
        assert manifest.dependencies == []
        assert manifest.trust_level == "standard"

    def test_full_manifest(self):
        """Test manifest with all fields."""
        manifest = PluginManifest(
            name="full-plugin",
            version="2.0.0",
            description="Full plugin",
            author="Test Author",
            homepage="https://example.com",
            repository="https://github.com/example/plugin",
            license="MIT",
            dependencies=["langchain>=0.1.0"],
            python_version=">=3.11",
            soothe_version=">=0.2.0",
            trust_level="trusted",
        )

        assert manifest.author == "Test Author"
        assert manifest.homepage == "https://example.com"
        assert manifest.license == "MIT"
        assert manifest.trust_level == "trusted"

    def test_manifest_default_timestamps(self):
        """Test manifest timestamps are auto-generated."""
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="Test",
        )

        assert isinstance(manifest.created_at, datetime)
        assert isinstance(manifest.updated_at, datetime)

    def test_manifest_extra_forbidden(self):
        """Test manifest rejects extra fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PluginManifest(
                name="test",
                version="1.0.0",
                description="Test",
                invalid_field="value",  # This should raise an error
            )

    def test_manifest_trust_level_validation(self):
        """Test trust level must be valid."""
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="Test",
            trust_level="built-in",
        )
        assert manifest.trust_level == "built-in"

        # Invalid trust level should raise error
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PluginManifest(
                name="test",
                version="1.0.0",
                description="Test",
                trust_level="invalid",  # type: ignore[arg-type]
            )


class TestPluginHealth:
    """Test PluginHealth model."""

    def test_healthy_status(self):
        """Test healthy plugin status."""
        health = PluginHealth(status="healthy", message="All systems operational")
        assert health.status == "healthy"
        assert health.message == "All systems operational"
        assert health.details == {}

    def test_unhealthy_status(self):
        """Test unhealthy plugin status."""
        health = PluginHealth(
            status="unhealthy",
            message="Database connection failed",
            details={"error": "Connection refused"},
        )
        assert health.status == "unhealthy"
        assert health.message == "Database connection failed"
        assert health.details == {"error": "Connection refused"}

    def test_degraded_status(self):
        """Test degraded plugin status."""
        health = PluginHealth(
            status="degraded",
            message="Partial functionality",
            details={"missing_features": ["search"]},
        )
        assert health.status == "degraded"

    def test_health_with_details(self):
        """Test health status with detailed information."""
        health = PluginHealth(
            status="healthy",
            message="All good",
            details={
                "tools_available": 5,
                "subagents_available": 2,
                "last_check": "2024-01-01T00:00:00Z",
            },
        )

        assert health.details["tools_available"] == 5
        assert health.details["subagents_available"] == 2


class TestPluginContext:
    """Test PluginContext model."""

    def test_plugin_context_creation(self):
        """Test creating plugin context."""
        mock_config = MagicMock(spec=SootheConfigProtocol)
        mock_config.resolve_model.return_value = "openai:gpt-4o-mini"

        mock_logger = MagicMock()
        mock_emit = MagicMock()

        context = PluginContext(
            config={"setting": "value"},
            soothe_config=mock_config,
            logger=mock_logger,
            emit_event=mock_emit,
        )

        assert context.config == {"setting": "value"}
        assert context.soothe_config == mock_config
        assert context.logger == mock_logger

    def test_plugin_context_config_access(self):
        """Test accessing config through context."""
        mock_config = MagicMock(spec=SootheConfigProtocol)
        mock_config.get_plugin_config.return_value = {"custom": "config"}

        mock_logger = MagicMock()
        mock_emit = MagicMock()

        context = PluginContext(
            config={},
            soothe_config=mock_config,
            logger=mock_logger,
            emit_event=mock_emit,
        )

        # Test accessing soothe_config methods
        mock_config.resolve_model("default")
        mock_config.get_plugin_config("test-plugin")

        mock_config.resolve_model.assert_called_once_with("default")
        mock_config.get_plugin_config.assert_called_once_with("test-plugin")

    def test_plugin_context_emit_event(self):
        """Test emitting events through context."""
        mock_config = MagicMock(spec=SootheConfigProtocol)
        mock_logger = MagicMock()
        mock_emit = MagicMock()

        context = PluginContext(
            config={},
            soothe_config=mock_config,
            logger=mock_logger,
            emit_event=mock_emit,
        )

        # Emit event
        context.emit_event("plugin.loaded", {"status": "success"})

        mock_emit.assert_called_once_with("plugin.loaded", {"status": "success"})


class TestExceptions:
    """Test SDK exception hierarchy."""

    def test_exception_hierarchy(self):
        """Test exception inheritance."""
        assert issubclass(DiscoveryError, PluginError)
        assert issubclass(ValidationError, PluginError)
        assert issubclass(DependencyError, PluginError)
        assert issubclass(InitializationError, PluginError)
        assert issubclass(ToolCreationError, PluginError)
        assert issubclass(SubagentCreationError, PluginError)

    def test_plugin_error_message(self):
        """Test PluginError with message."""
        error = PluginError("Test error message")
        assert str(error) == "Test error message"

    def test_discovery_error(self):
        """Test DiscoveryError."""
        error = DiscoveryError("Plugin not found")
        assert isinstance(error, PluginError)
        assert str(error) == "Plugin not found"

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid manifest")
        assert isinstance(error, PluginError)

    def test_dependency_error(self):
        """Test DependencyError."""
        error = DependencyError("Missing dependency: langchain")
        assert isinstance(error, PluginError)

    def test_initialization_error(self):
        """Test InitializationError."""
        error = InitializationError("Failed to initialize plugin")
        assert isinstance(error, PluginError)

    def test_tool_creation_error(self):
        """Test ToolCreationError."""
        error = ToolCreationError("Invalid tool signature")
        assert isinstance(error, PluginError)

    def test_subagent_creation_error(self):
        """Test SubagentCreationError."""
        error = SubagentCreationError("Failed to create subagent")
        assert isinstance(error, PluginError)

    def test_exception_chaining(self):
        """Test exception chaining."""
        original = ValueError("Original error")
        error = PluginError("Wrapped error")
        error.__cause__ = original

        assert error.__cause__ == original


class TestIntegration:
    """Integration tests for SDK components."""

    @pytest.mark.asyncio
    async def test_full_plugin_integration(self):
        """Test complete plugin with all features."""

        @plugin(
            name="integration-plugin",
            version="1.0.0",
            description="Integration test plugin",
            author="Test Author",
            dependencies=["langchain>=0.1.0"],
            trust_level="trusted",
        )
        class IntegrationPlugin:
            @tool(name="calculate", description="Perform calculation")
            def calculate(self, operation: str, a: int, b: int) -> int:
                if operation == "add":
                    return a + b
                if operation == "multiply":
                    return a * b
                msg = f"Unknown operation: {operation}"
                raise ValueError(msg)

            @tool_group(name="utils", description="Utility tools")
            class Utils:
                @tool(name="format", description="Format string")
                def format_string(self, template: str, **kwargs) -> str:
                    return template.format(**kwargs)

            @subagent(
                name="assistant",
                description="Helper subagent",
                model="openai:gpt-4o-mini",
            )
            async def create_assistant(self, model, config, context):
                return {
                    "name": "assistant",
                    "description": "Helper subagent",
                    "runnable": MagicMock(),
                }

        # Create instance
        instance = IntegrationPlugin()

        # Verify manifest
        assert instance.manifest.name == "integration-plugin"
        assert instance.manifest.version == "1.0.0"
        assert instance.manifest.author == "Test Author"
        assert instance.manifest.dependencies == ["langchain>=0.1.0"]
        assert instance.manifest.trust_level == "trusted"

        # Verify tools
        tools = instance.get_tools()
        assert len(tools) == 1  # Only top-level tools
        assert tools[0]._tool_name == "calculate"

        # Test tool functionality
        assert instance.calculate("add", 5, 3) == 8
        assert instance.calculate("multiply", 5, 3) == 15

        # Test tool group
        utils = instance.Utils()
        assert utils.format_string("Hello {name}", name="World") == "Hello World"

        # Verify subagents
        subagents = instance.get_subagents()
        assert len(subagents) == 1
        assert subagents[0]._subagent_name == "assistant"

        # Test subagent factory
        result = await instance.create_assistant(
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        assert result["name"] == "assistant"

    def test_plugin_composition(self):
        """Test composing multiple plugins."""

        @plugin(name="base", version="1.0.0", description="Base")
        class BasePlugin:
            @tool(name="base_op", description="Base operation")
            def base_op(self, x: int) -> int:
                return x

        @plugin(name="extended", version="1.0.0", description="Extended")
        class ExtendedPlugin:
            @tool(name="extended_op", description="Extended operation")
            def extended_op(self, x: int) -> int:
                return x * 2

        base = BasePlugin()
        extended = ExtendedPlugin()

        # Both should work independently
        assert base.base_op(5) == 5
        assert extended.extended_op(5) == 10

    @pytest.mark.asyncio
    async def test_error_handling_in_tools(self):
        """Test error handling in tool execution."""

        @plugin(name="test", version="1.0.0", description="Test")
        class ErrorHandlingPlugin:
            @tool(name="divide", description="Divide numbers")
            def divide(self, a: int, b: int) -> float:
                if b == 0:
                    raise ValueError("Cannot divide by zero")
                return a / b

        instance = ErrorHandlingPlugin()

        # Valid operation
        result = instance.divide(10, 2)
        assert result == 5.0

        # Error case
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            instance.divide(10, 0)

    def test_plugin_with_state(self):
        """Test plugin that maintains state."""

        @plugin(name="stateful", version="1.0.0", description="Stateful plugin")
        class StatefulPlugin:
            def __init__(self):
                self.counter = 0

            @tool(name="increment", description="Increment counter")
            def increment(self) -> int:
                self.counter += 1
                return self.counter

            @tool(name="get_count", description="Get counter value")
            def get_count(self) -> int:
                return self.counter

        instance = StatefulPlugin()

        assert instance.increment() == 1
        assert instance.increment() == 2
        assert instance.get_count() == 2


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_plugin_name_with_hyphens(self):
        """Test plugin names with hyphens."""

        @plugin(name="my-awesome-plugin", version="1.0.0", description="Test")
        class MyPlugin:
            pass

        instance = MyPlugin()
        assert instance.manifest.name == "my-awesome-plugin"

    def test_empty_dependencies(self):
        """Test plugin with empty dependencies list."""

        @plugin(name="test", version="1.0.0", description="Test", dependencies=[])
        class NoDepsPlugin:
            pass

        instance = NoDepsPlugin()
        assert instance.manifest.dependencies == []

    def test_tool_with_no_description(self):
        """Test tool without description (uses default)."""

        @plugin(name="test", version="1.0.0", description="Test")
        class NoDescPlugin:
            @tool(name="minimal_tool", description="")
            def minimal_tool(self):
                return "result"

        instance = NoDescPlugin()
        assert instance.minimal_tool._tool_description == ""

    def test_private_methods_ignored(self):
        """Test that private methods are not picked up as tools."""

        @plugin(name="test", version="1.0.0", description="Test")
        class PrivatePlugin:
            @tool(name="public_tool", description="Public")
            def public_tool(self):
                return "public"

            def _private_method(self):
                return "private"

            def __dunder_method__(self):
                return "dunder"

        instance = PrivatePlugin()
        tools = instance.get_tools()

        assert len(tools) == 1
        assert tools[0]._tool_name == "public_tool"

    @pytest.mark.asyncio
    async def test_subagent_factory_exception(self):
        """Test exception in subagent factory."""

        @plugin(name="test", version="1.0.0", description="Test")
        class FailingPlugin:
            @subagent(name="failing", description="Failing subagent")
            async def create_failing(self, model, config, context):
                raise RuntimeError("Subagent creation failed")

        instance = FailingPlugin()

        with pytest.raises(RuntimeError, match="Subagent creation failed"):
            await instance.create_failing(MagicMock(), MagicMock(), MagicMock())

    def test_version_formats(self):
        """Test different version formats."""
        versions = ["1.0.0", "0.1.0-alpha", "2.0.0-beta.1", "1.0.0-rc.1+build.123"]

        for version in versions:

            @plugin(name="test", version=version, description="Test")
            class VersionPlugin:
                pass

            instance = VersionPlugin()
            assert instance.manifest.version == version

    def test_tool_with_varargs(self):
        """Test tool with *args and **kwargs."""

        @plugin(name="test", version="1.0.0", description="Test")
        class VarArgsPlugin:
            @tool(name="flexible", description="Flexible tool")
            def flexible_tool(self, *args, **kwargs):
                return {"args": args, "kwargs": kwargs}

        instance = VarArgsPlugin()
        result = instance.flexible_tool(1, 2, 3, key="value")

        assert result["args"] == (1, 2, 3)
        assert result["kwargs"] == {"key": "value"}
