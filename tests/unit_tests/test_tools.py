"""Tests for custom Soothe tools."""

from soothe.tools.jina import JinaReaderTool, create_jina_tools
from soothe.tools.serper import SerperSearchTool, create_serper_tools
from soothe.tools.tabular import (
    TabularColumnsTool,
    TabularQualityTool,
    TabularSummaryTool,
    create_tabular_tools,
)
from soothe.tools.video import VideoInfoTool, create_video_tools


class TestJinaTools:
    def test_create_returns_list(self):
        tools = create_jina_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], JinaReaderTool)

    def test_tool_metadata(self):
        tool = JinaReaderTool()
        assert tool.name == "jina_get_web_content"
        assert "web" in tool.description.lower()


class TestSerperTools:
    def test_create_returns_list(self):
        tools = create_serper_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], SerperSearchTool)

    def test_tool_metadata(self):
        tool = SerperSearchTool()
        assert tool.name == "serper_search"
        assert "search" in tool.description.lower()
        assert "images" in tool.description.lower()
        assert "scholar" in tool.description.lower()


class TestVideoTools:
    def test_create_returns_list(self):
        tools = create_video_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], VideoInfoTool)

    def test_nonexistent_file(self):
        tool = VideoInfoTool()
        result = tool._run("/nonexistent/path.mp4")
        assert "error" in result


class TestTabularTools:
    def test_create_returns_list(self):
        tools = create_tabular_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "get_tabular_columns" in names
        assert "get_data_summary" in names
        assert "validate_data_quality" in names

    def test_tool_types(self):
        tools = create_tabular_tools()
        types = {type(t) for t in tools}
        assert TabularColumnsTool in types
        assert TabularSummaryTool in types
        assert TabularQualityTool in types
