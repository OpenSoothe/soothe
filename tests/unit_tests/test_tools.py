"""Tests for custom Soothe tools."""

import pytest

from soothe.tools._internal.jina import JinaReaderTool
from soothe.tools._internal.serper import SerperSearchTool
from soothe.tools._internal.tabular import (
    TabularColumnsTool,
    TabularQualityTool,
    TabularSummaryTool,
    create_tabular_tools,
)
from soothe.tools._internal.wizsearch import (
    WizsearchCrawlPageTool,
    WizsearchSearchTool,
    _normalize_engines,
    create_wizsearch_tools,
)
from soothe.tools.datetime import CurrentDateTimeTool, create_datetime_tools
from soothe.tools.video import VideoInfoTool, create_video_tools
from soothe.tools.websearch import WebCrawlTool, WebSearchTool, create_websearch_tools


class TestDatetimeTools:
    def test_create_returns_list(self) -> None:
        tools = create_datetime_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], CurrentDateTimeTool)

    def test_tool_metadata(self) -> None:
        tool = CurrentDateTimeTool()
        assert tool.name == "current_datetime"
        assert "date" in tool.description.lower()
        assert "time" in tool.description.lower()

    def test_returns_expected_keys(self) -> None:
        tool = CurrentDateTimeTool()
        result = tool._run()
        assert "date" in result
        assert "time" in result
        assert "day" in result
        assert "timezone" in result
        assert "iso" in result

    def test_date_format(self) -> None:
        tool = CurrentDateTimeTool()
        result = tool._run()
        parts = result["date"].split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4


class TestJinaTools:
    """Tests for internal Jina reader tool."""

    def test_tool_metadata(self) -> None:
        tool = JinaReaderTool()
        assert tool.name == "jina_get_web_content"
        assert "web" in tool.description.lower()


class TestSerperTools:
    """Tests for internal Serper search tool."""

    def test_tool_metadata(self) -> None:
        tool = SerperSearchTool()
        assert tool.name == "serper_search"
        assert "search" in tool.description.lower()
        assert "images" in tool.description.lower()
        assert "scholar" in tool.description.lower()


class TestWebsearchTools:
    """Tests for unified websearch tool with dynamic backend selection."""

    def test_create_returns_list(self) -> None:
        tools = create_websearch_tools()
        assert len(tools) == 2
        assert isinstance(tools[0], WebSearchTool)
        assert isinstance(tools[1], WebCrawlTool)

    def test_search_tool_metadata(self) -> None:
        tool = WebSearchTool()
        assert tool.name == "websearch"
        assert "search" in tool.description.lower()

    def test_crawl_tool_metadata(self) -> None:
        tool = WebCrawlTool()
        assert tool.name == "websearch_crawl"
        assert "extract" in tool.description.lower() or "content" in tool.description.lower()


class TestWizsearchTools:
    def test_create_returns_list(self) -> None:
        tools = create_wizsearch_tools()
        assert len(tools) == 2
        types = {type(tool) for tool in tools}
        assert WizsearchSearchTool in types
        assert WizsearchCrawlPageTool in types

    def test_tool_metadata(self) -> None:
        search_tool = WizsearchSearchTool()
        assert search_tool.name == "wizsearch_search"
        assert "multiple engines" in search_tool.description.lower()

        crawl_tool = WizsearchCrawlPageTool()
        assert crawl_tool.name == "wizsearch_crawl_page"
        assert "crawl" in crawl_tool.description.lower()

    def test_missing_dependency_error(self, monkeypatch) -> None:
        import soothe.tools._internal.wizsearch._helpers as wizsearch_helpers

        monkeypatch.setattr(wizsearch_helpers, "WIZSEARCH_AVAILABLE", False)
        tool = WizsearchSearchTool()
        with pytest.raises(ImportError, match="wizsearch package is not installed"):
            tool._run(query="latest ai research")

    def test_default_engines(self, monkeypatch) -> None:
        import soothe.tools._internal.wizsearch._helpers as wizsearch_helpers

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

        monkeypatch.setattr(wizsearch_helpers, "WIZSEARCH_AVAILABLE", True)

        import wizsearch as _wiz_pkg

        monkeypatch.setattr(_wiz_pkg, "WizSearchConfig", DummyConfig)
        monkeypatch.setattr(_wiz_pkg, "WizSearch", DummySearch)

        tool = WizsearchSearchTool()
        _ = tool._run(query="ai agents")

        assert captured["enabled_engines"] == ["tavily", "duckduckgo"]

    def test_custom_engines_via_config(self, monkeypatch) -> None:
        """Test that custom engines can be set via config parameter."""
        import soothe.tools._internal.wizsearch._helpers as wizsearch_helpers

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

        monkeypatch.setattr(wizsearch_helpers, "WIZSEARCH_AVAILABLE", True)

        import wizsearch as _wiz_pkg

        monkeypatch.setattr(_wiz_pkg, "WizSearchConfig", DummyConfig)
        monkeypatch.setattr(_wiz_pkg, "WizSearch", DummySearch)

        # Test with custom engines
        tool = WizsearchSearchTool(
            config={
                "default_engines": ["tavily", "duckduckgo"],
                "max_results_per_engine": 5,
                "timeout": 20,
            }
        )
        _ = tool._run(query="test query")

        assert captured["enabled_engines"] == ["tavily", "duckduckgo"]
        assert captured["max_results_per_engine"] == 5
        assert captured["timeout"] == 20

    def test_create_wizsearch_tools_with_config(self) -> None:
        """Test create_wizsearch_tools factory with config."""
        config = {
            "default_engines": ["tavily"],
            "max_results_per_engine": 15,
            "timeout": 45,
        }
        tools = create_wizsearch_tools(config)

        assert len(tools) == 2
        assert isinstance(tools[0], WizsearchSearchTool)
        assert isinstance(tools[1], WizsearchCrawlPageTool)
        assert tools[0].default_engines == ["tavily"]
        assert tools[0].default_max_results_per_engine == 15
        assert tools[0].default_timeout == 45


class TestNormalizeEngines:
    """Test _normalize_engines handles various LLM output formats."""

    def test_none_returns_none(self) -> None:
        assert _normalize_engines(None) is None

    def test_list_passthrough(self) -> None:
        assert _normalize_engines(["tavily", "duckduckgo"]) == ["tavily", "duckduckgo"]

    def test_comma_separated_string(self) -> None:
        assert _normalize_engines("tavily, duckduckgo") == ["tavily", "duckduckgo"]

    def test_json_array_string(self) -> None:
        assert _normalize_engines('["google", "bing"]') == ["google", "bing"]

    def test_json_array_no_spaces(self) -> None:
        assert _normalize_engines('["tavily","duckduckgo"]') == ["tavily", "duckduckgo"]

    def test_single_engine_string(self) -> None:
        assert _normalize_engines("tavily") == ["tavily"]

    def test_empty_list_returns_none(self) -> None:
        assert _normalize_engines([]) is None

    def test_empty_string_returns_none(self) -> None:
        assert _normalize_engines("") is None


class TestVideoTools:
    def test_create_returns_list(self) -> None:
        tools = create_video_tools()
        assert len(tools) == 2  # VideoInfoTool and VideoAnalysisTool
        assert isinstance(tools[1], VideoInfoTool)

    def test_nonexistent_file(self) -> None:
        tool = VideoInfoTool()
        result = tool._run("/nonexistent/path.mp4")
        assert "error" in result


class TestTabularTools:
    def test_create_returns_list(self) -> None:
        tools = create_tabular_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "get_tabular_columns" in names
        assert "get_data_summary" in names
        assert "validate_data_quality" in names

    def test_tool_types(self) -> None:
        tools = create_tabular_tools()
        types = {type(t) for t in tools}
        assert TabularColumnsTool in types
        assert TabularSummaryTool in types
        assert TabularQualityTool in types
