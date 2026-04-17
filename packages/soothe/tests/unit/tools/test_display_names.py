"""Unit tests for tool display name auto-conversion."""

from soothe.tools.display_names import get_tool_display_name


def test_auto_conversion_basic():
    """Test basic snake_case to PascalCase conversion."""
    assert get_tool_display_name("read_file") == "ReadFile"
    assert get_tool_display_name("run_command") == "RunCommand"
    assert get_tool_display_name("my_custom_tool") == "MyCustomTool"


def test_auto_conversion_simple():
    """Test conversion of simple names."""
    assert get_tool_display_name("ls") == "Ls"
    assert get_tool_display_name("grep") == "Grep"
    assert get_tool_display_name("cat") == "Cat"


def test_auto_conversion_complex():
    """Test conversion of complex names."""
    assert get_tool_display_name("inspect_data") == "InspectData"
    assert get_tool_display_name("check_data_quality") == "CheckDataQuality"
    assert get_tool_display_name("extract_text_from_image") == "ExtractTextFromImage"


def test_auto_conversion_edge_cases():
    """Test edge cases."""
    # Single word
    assert get_tool_display_name("research") == "Research"

    # Multiple underscores
    assert get_tool_display_name("a_b_c_d") == "ABCD"

    # Empty string
    assert get_tool_display_name("") == ""


def test_tool_decorator_auto_conversion():
    """Test @tool decorator uses auto-conversion."""
    from soothe_sdk.plugin import tool

    # Define a class to hold the tool
    class TestPlugin:
        @tool(name="auto_tool", description="Auto-converted tool")
        def auto_tool(self, data: str) -> str:
            """An auto tool."""
            return data

    # Get the wrapped method
    plugin = TestPlugin()
    wrapped_tool = plugin.auto_tool

    # Tool metadata should be set
    assert hasattr(wrapped_tool, "_tool_name")
    assert wrapped_tool._tool_name == "auto_tool"

    # But display name auto-converts
    assert get_tool_display_name("auto_tool") == "AutoTool"


def test_subagent_decorator_auto_conversion():
    """Test @subagent decorator uses auto-conversion."""
    from soothe_sdk.plugin import subagent

    # Define a class to hold the subagent
    class TestPlugin:
        @subagent(name="my_agent", description="Test agent")
        async def create_agent(self, model, config, context):
            return {"name": "my_agent", "runnable": None}

    # Get the wrapped method
    plugin = TestPlugin()
    wrapped_subagent = plugin.create_agent

    # Should not have _subagent_display_name attribute (removed)
    assert not hasattr(wrapped_subagent, "_subagent_display_name")

    # But the name should auto-convert
    assert get_tool_display_name("my_agent") == "MyAgent"
