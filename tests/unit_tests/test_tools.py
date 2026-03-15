"""Tests for custom Soothe tools."""

import pytest

from soothe.tools.jina import JinaReaderTool, create_jina_tools
from soothe.tools.serper import SerperSearchTool, create_serper_tools
from soothe.tools.tabular import (
    TabularColumnsTool,
    TabularQualityTool,
    TabularSummaryTool,
    create_tabular_tools,
)
from soothe.tools.video import VideoInfoTool, create_video_tools
from soothe.tools.wizsearch import (
    WizsearchCrawlPageTool,
    WizsearchSearchTool,
    create_wizsearch_tools,
)


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


class TestWizsearchTools:
    def test_create_returns_list(self):
        tools = create_wizsearch_tools()
        assert len(tools) == 2
        types = {type(tool) for tool in tools}
        assert WizsearchSearchTool in types
        assert WizsearchCrawlPageTool in types

    def test_tool_metadata(self):
        search_tool = WizsearchSearchTool()
        assert search_tool.name == "wizsearch_search"
        assert "multiple engines" in search_tool.description.lower()

        crawl_tool = WizsearchCrawlPageTool()
        assert crawl_tool.name == "wizsearch_crawl_page"
        assert "crawl" in crawl_tool.description.lower()

    def test_missing_dependency_error(self, monkeypatch):
        import soothe.tools.wizsearch as wizsearch_mod

        monkeypatch.setattr(wizsearch_mod, "WIZSEARCH_AVAILABLE", False)
        tool = WizsearchSearchTool()
        with pytest.raises(ImportError, match="wizsearch package is not installed"):
            tool._run(query="latest ai research")

    def test_default_engine_is_tavily(self, monkeypatch):
        import soothe.tools.wizsearch as wizsearch_mod

        captured: dict[str, object] = {}

        class DummyConfig:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        class DummySearch:
            def __init__(self, config: object) -> None:
                self.config = config

            async def search(self, query: str) -> object:
                class DummyResult:
                    def __init__(self, query_text: str) -> None:
                        self.query = query_text
                        self.answer = None
                        self.sources = []
                        self.response_time = 0.0
                        self.metadata = {}

                return DummyResult(query)

        monkeypatch.setattr(wizsearch_mod, "WIZSEARCH_AVAILABLE", True)
        monkeypatch.setattr(wizsearch_mod, "WizSearchConfig", DummyConfig)
        monkeypatch.setattr(wizsearch_mod, "WizSearch", DummySearch)

        tool = WizsearchSearchTool()
        _ = tool._run(query="ai agents")

        assert captured["enabled_engines"] == ["tavily"]


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
