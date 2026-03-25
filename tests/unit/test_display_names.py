"""Unit tests for tool display name registration system."""

import pytest

from soothe.tools.display_names import (
    DISPLAY_NAME_REGISTRY,
    get_tool_display_name,
    register_tool_display_name,
)


def test_register_and_lookup():
    """Test basic registration and lookup."""
    # Register a custom display name
    register_tool_display_name("test_tool", "TestTool")

    # Lookup should return registered name
    assert get_tool_display_name("test_tool") == "TestTool"

    # Clean up
    DISPLAY_NAME_REGISTRY._names.pop("test_tool", None)


def test_override_builtin():
    """Test that plugins can override built-in names."""
    # Built-in: "read_file" -> "ReadFile"
    original_name = get_tool_display_name("read_file")
    assert original_name == "ReadFile"

    # Register custom display name
    register_tool_display_name("read_file", "CustomReadFile")

    # Should return custom name
    assert get_tool_display_name("read_file") == "CustomReadFile"

    # Clean up (restore original)
    DISPLAY_NAME_REGISTRY._names.pop("read_file", None)
    assert get_tool_display_name("read_file") == "ReadFile"


def test_auto_conversion_fallback():
    """Test auto-conversion for unregistered names."""
    # Unregistered tool should auto-convert
    assert get_tool_display_name("new_tool") == "NewTool"
    assert get_tool_display_name("my_custom_tool") == "MyCustomTool"
    assert get_tool_display_name("another_example") == "AnotherExample"


def test_registry_list_all():
    """Test listing all registered display names."""
    # Clear registry for clean test
    original_names = DISPLAY_NAME_REGISTRY.list_all()
    DISPLAY_NAME_REGISTRY._names.clear()

    # Register some names
    register_tool_display_name("tool_a", "ToolA")
    register_tool_display_name("tool_b", "ToolB")

    # List all
    all_names = DISPLAY_NAME_REGISTRY.list_all()
    assert all_names == {"tool_a": "ToolA", "tool_b": "ToolB"}

    # Restore original names
    DISPLAY_NAME_REGISTRY._names.clear()
    for name, display in original_names.items():
        DISPLAY_NAME_REGISTRY.register(name, display)


def test_multiple_registrations_last_wins():
    """Test that last registration wins for duplicate names."""
    # Register same tool twice
    register_tool_display_name("duplicate_tool", "FirstVersion")
    register_tool_display_name("duplicate_tool", "SecondVersion")

    # Should return last registered name
    assert get_tool_display_name("duplicate_tool") == "SecondVersion"

    # Clean up
    DISPLAY_NAME_REGISTRY._names.pop("duplicate_tool", None)


def test_builtin_names_registered():
    """Test that all built-in names are registered at module load."""
    # These should all be registered
    builtin_names = [
        "write_file",
        "run_command",
        "inspect_data",
        "search_web",
    ]

    for name in builtin_names:
        display = get_tool_display_name(name)
        # Should be in registry
        assert name in DISPLAY_NAME_REGISTRY.list_all()
        assert DISPLAY_NAME_REGISTRY.get(name) == display


def test_tool_decorator_display_name():
    """Test @tool decorator auto-registration of display names."""
    from soothe_sdk.decorators.tool import tool

    # Define a class to hold the tool
    class TestPlugin:
        @tool(name="custom_tool", display_name="CustomTool")
        def custom_tool(self, x: int) -> int:
            """A custom tool."""
            return x * 2

    # Get the wrapped method
    plugin = TestPlugin()
    wrapped_tool = plugin.custom_tool

    # Display name should be registered
    assert get_tool_display_name("custom_tool") == "CustomTool"

    # Metadata should be stored on wrapper
    assert hasattr(wrapped_tool, "_tool_display_name")
    assert wrapped_tool._tool_display_name == "CustomTool"
    assert wrapped_tool._tool_name == "custom_tool"

    # Clean up
    DISPLAY_NAME_REGISTRY._names.pop("custom_tool", None)


def test_tool_decorator_auto_conversion():
    """Test @tool decorator auto-conversion when no display_name provided."""
    from soothe_sdk.decorators.tool import tool

    # Define a class to hold the tool
    class TestPlugin:
        @tool(name="auto_tool", description="Auto-converted tool")
        def auto_tool(self, data: str) -> str:
            """An auto tool."""
            return data

    # Get the wrapped method
    plugin = TestPlugin()
    wrapped_tool = plugin.auto_tool

    # Should use auto-converted name
    assert hasattr(wrapped_tool, "_tool_display_name")
    assert wrapped_tool._tool_display_name == "AutoTool"

    # Should NOT register (uses fallback auto-conversion)
    # (Because we only register when display_name is explicitly provided)
    assert "auto_tool" not in DISPLAY_NAME_REGISTRY.list_all()
