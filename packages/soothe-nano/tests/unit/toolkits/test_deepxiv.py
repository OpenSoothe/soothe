"""Unit tests for DeepXiv toolkit.

Tests DeepXiv academic paper search and reading tools with mocked SDK.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.toolkits.deepxiv import (
    DeepxivGetFullPaperInput,
    DeepxivGetFullPaperTool,
    DeepxivPaperBriefInput,
    DeepxivPaperBriefTool,
    DeepxivPaperMetadataInput,
    DeepxivPaperMetadataTool,
    DeepxivPlugin,
    DeepxivReadSectionInput,
    DeepxivReadSectionTool,
    DeepxivSearchInput,
    DeepxivSearchTool,
    DeepxivToolkit,
    DeepxivTrendingInput,
    DeepxivTrendingTool,
    DeepxivWebsearchInput,
    DeepxivWebsearchTool,
    _deepxiv_exception_message,
    _safe_call,
    resolve_deepxiv_token,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_reader():
    """Create a mock DeepXiv Reader instance."""
    reader = MagicMock()
    return reader


@pytest.fixture
def toolkit(mock_reader):
    """Create DeepxivToolkit with mocked reader."""
    toolkit = DeepxivToolkit(token="test_token", timeout=30, max_retries=2)
    toolkit._reader = mock_reader
    yield toolkit


@pytest.fixture
def search_tool(toolkit):
    """Create DeepxivSearchTool instance."""
    return DeepxivSearchTool(toolkit=toolkit)


@pytest.fixture
def brief_tool(toolkit):
    """Create DeepxivPaperBriefTool instance."""
    return DeepxivPaperBriefTool(toolkit=toolkit)


@pytest.fixture
def metadata_tool(toolkit):
    """Create DeepxivPaperMetadataTool instance."""
    return DeepxivPaperMetadataTool(toolkit=toolkit)


@pytest.fixture
def read_section_tool(toolkit):
    """Create DeepxivReadSectionTool instance."""
    return DeepxivReadSectionTool(toolkit=toolkit)


@pytest.fixture
def full_paper_tool(toolkit):
    """Create DeepxivGetFullPaperTool instance."""
    return DeepxivGetFullPaperTool(toolkit=toolkit)


@pytest.fixture
def trending_tool(toolkit):
    """Create DeepxivTrendingTool instance."""
    return DeepxivTrendingTool(toolkit=toolkit)


@pytest.fixture
def websearch_tool(toolkit):
    """Create DeepxivWebsearchTool instance."""
    return DeepxivWebsearchTool(toolkit=toolkit)


# -----------------------------------------------------------------------------
# Input Schema Tests
# -----------------------------------------------------------------------------


class TestInputSchemas:
    """Test Pydantic input schemas for all DeepXiv tools."""

    def test_search_input_schema(self):
        """Test DeepxivSearchInput schema."""
        # Minimal valid input
        data = DeepxivSearchInput(query="machine learning")
        assert data.query == "machine learning"
        assert data.size == 10  # default
        assert data.source is None  # default

        # Full input
        data = DeepxivSearchInput(
            query="transformer architecture",
            size=20,
            source="arxiv",
            categories=["cs.AI", "cs.CL"],
            authors=["John Doe"],
            organizations=["MIT"],
            date_from="2024-01-01",
            date_to="2024-12-31",
            min_citation=10,
        )
        assert data.size == 20
        assert data.source == "arxiv"
        assert data.categories == ["cs.AI", "cs.CL"]

    def test_paper_brief_input_schema(self):
        """Test DeepxivPaperBriefInput schema."""
        data = DeepxivPaperBriefInput(paper_id="2409.05591")
        assert data.paper_id == "2409.05591"
        assert data.source == "arxiv"  # default

        data = DeepxivPaperBriefInput(paper_id="12345", source="pmc")
        assert data.source == "pmc"

    def test_paper_metadata_input_schema(self):
        """Test DeepxivPaperMetadataInput schema."""
        data = DeepxivPaperMetadataInput(paper_id="2409.05591")
        assert data.paper_id == "2409.05591"
        assert data.source == "arxiv"  # default

    def test_read_section_input_schema(self):
        """Test DeepxivReadSectionInput schema."""
        data = DeepxivReadSectionInput(paper_id="2409.05591", section_name="Introduction")
        assert data.paper_id == "2409.05591"
        assert data.section_name == "Introduction"
        assert data.source == "arxiv"  # default

    def test_get_full_paper_input_schema(self):
        """Test DeepxivGetFullPaperInput schema."""
        data = DeepxivGetFullPaperInput(paper_id="2409.05591")
        assert data.paper_id == "2409.05591"
        assert data.source == "arxiv"  # default

    def test_trending_input_schema(self):
        """Test DeepxivTrendingInput schema."""
        data = DeepxivTrendingInput()
        assert data.days == 7  # default
        assert data.limit == 10  # default

        data = DeepxivTrendingInput(days=30, limit=50)
        assert data.days == 30
        assert data.limit == 50

    def test_websearch_input_schema(self):
        """Test DeepxivWebsearchInput schema."""
        data = DeepxivWebsearchInput(query="neural networks")
        assert data.query == "neural networks"


# -----------------------------------------------------------------------------
# Toolkit Tests
# -----------------------------------------------------------------------------


class TestDeepxivToolkit:
    """Test DeepxivToolkit initialization and configuration."""

    def test_toolkit_initialization(self):
        """Test toolkit initialization with parameters."""
        toolkit = DeepxivToolkit(token="my_token", timeout=45, max_retries=5)
        assert toolkit.token == "my_token"
        assert toolkit.timeout == 45
        assert toolkit.max_retries == 5
        assert toolkit._reader is None

    def test_toolkit_default_values(self):
        """Test toolkit initialization with default values."""
        with patch.dict("os.environ", {"DEEPXIV_API_KEY": "", "DEEPXIV_TOKEN": ""}, clear=True):
            toolkit = DeepxivToolkit()
            assert toolkit.token is None
            assert toolkit.timeout == 60
            assert toolkit.max_retries == 3

    def test_get_tools_returns_seven_tools(self, toolkit):
        """Test get_tools returns all 7 DeepXiv tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 7

        tool_names = {t.name for t in tools}
        expected_names = {
            "deepxiv_search",
            "deepxiv_paper_brief",
            "deepxiv_paper_metadata",
            "deepxiv_read_section",
            "deepxiv_get_full_paper",
            "deepxiv_trending",
            "deepxiv_websearch",
        }
        assert tool_names == expected_names


# -----------------------------------------------------------------------------
# Search Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivSearchTool:
    """Test DeepxivSearchTool functionality."""

    def test_tool_metadata(self, search_tool):
        """Test tool name and description."""
        assert search_tool.name == "deepxiv_search"
        assert "search" in search_tool.description.lower()
        assert "arxiv" in search_tool.description.lower()

    def test_args_schema(self, search_tool):
        """Test args schema is set correctly."""
        assert search_tool.args_schema == DeepxivSearchInput

    def test_search_with_results(self, search_tool, toolkit):
        """Test search returns formatted results."""
        mock_result = {
            "result": [
                {
                    "arxiv_id": "2409.05591",
                    "title": "Test Paper Title",
                    "abstract": "This is a test abstract that describes the paper content.",
                    "score": 0.95,
                    "citation_count": 42,
                    "authors": [{"name": "John Doe"}, {"name": "Jane Smith"}],
                    "categories": ["cs.AI", "cs.CL"],
                }
            ],
            "total_count": 1,
        }
        toolkit._reader.search.return_value = mock_result

        result = search_tool._run(query="test query")

        assert "2409.05591" in result
        assert "Test Paper Title" in result
        assert "John Doe" in result
        assert "cs.AI" in result
        assert "Citations: 42" in result
        toolkit._reader.search.assert_called_once()

    def test_search_no_results(self, search_tool, toolkit):
        """Test search with no results."""
        toolkit._reader.search.return_value = {"result": [], "total_count": 0}

        result = search_tool._run(query="nonexistent query")

        assert "No papers found" in result

    def test_search_empty_result(self, search_tool, toolkit):
        """Test search with empty result."""
        toolkit._reader.search.return_value = None

        result = search_tool._run(query="test")

        assert "No papers found" in result

    def test_search_with_filters(self, search_tool, toolkit):
        """Test search with all filter parameters."""
        toolkit._reader.search.return_value = {"result": [], "total_count": 0}

        search_tool._run(
            query="transformer",
            size=20,
            source="arxiv",
            categories=["cs.AI"],
            authors=["John Doe"],
            organizations=["MIT"],
            date_from="2024-01-01",
            date_to="2024-12-31",
            min_citation=10,
        )

        call_args = toolkit._reader.search.call_args[1]
        assert call_args["query"] == "transformer"
        assert call_args["size"] == 20
        assert call_args["source"] == "arxiv"
        assert call_args["categories"] == ["cs.AI"]
        assert call_args["authors"] == ["John Doe"]
        assert call_args["organizations"] == ["MIT"]
        assert call_args["date_from"] == "2024-01-01"
        assert call_args["date_to"] == "2024-12-31"
        assert call_args["min_citation"] == 10

    def test_search_size_limit(self, search_tool, toolkit):
        """Test search size is capped at 50."""
        toolkit._reader.search.return_value = {"result": [], "total_count": 0}

        search_tool._run(query="test", size=100)

        call_args = toolkit._reader.search.call_args[1]
        assert call_args["size"] == 50  # capped

    def test_search_multiple_authors_truncation(self, search_tool, toolkit):
        """Test author list truncation for more than 3 authors."""
        mock_result = {
            "result": [
                {
                    "arxiv_id": "2409.05591",
                    "title": "Test Paper",
                    "abstract": "Abstract text",
                    "score": 0.9,
                    "citation_count": 10,
                    "authors": [
                        {"name": "Author 1"},
                        {"name": "Author 2"},
                        {"name": "Author 3"},
                        {"name": "Author 4"},
                    ],
                    "categories": [],
                }
            ],
            "total_count": 1,
        }
        toolkit._reader.search.return_value = mock_result

        result = search_tool._run(query="test")

        assert "Author 1, Author 2, Author 3 et al." in result

    def test_search_string_authors(self, search_tool, toolkit):
        """Test search when API returns authors as plain strings."""
        mock_result = {
            "result": [
                {
                    "arxiv_id": "2409.05591",
                    "title": "Test Paper",
                    "abstract": "Abstract text",
                    "score": 0.9,
                    "citation_count": 10,
                    "authors": ["Alice Smith", "Bob Jones"],
                    "categories": [],
                }
            ],
            "total_count": 1,
        }
        toolkit._reader.search.return_value = mock_result

        result = search_tool._run(query="test")

        assert "Alice Smith, Bob Jones" in result

    async def test_arun_delegates_to_run(self, search_tool, toolkit):
        """Test async run delegates to sync run."""
        toolkit._reader.search.return_value = {"result": [], "total_count": 0}

        result = await search_tool._arun(query="test")

        assert "No papers found" in result


# -----------------------------------------------------------------------------
# Paper Brief Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivPaperBriefTool:
    """Test DeepxivPaperBriefTool functionality."""

    def test_tool_metadata(self, brief_tool):
        """Test tool name and description."""
        assert brief_tool.name == "deepxiv_paper_brief"
        assert "summary" in brief_tool.description.lower()

    def test_get_paper_brief(self, brief_tool, toolkit):
        """Test getting paper brief."""
        mock_result = {
            "title": "Test Paper Title",
            "tldr": "A summary of the paper",
            "keywords": ["machine learning", "neural networks"],
            "citations": 100,
            "publish_at": "2024-01-15",
            "pdf_url": "https://arxiv.org/pdf/2409.05591",
            "github_url": "https://github.com/test/repo",
        }
        toolkit._reader.brief.return_value = mock_result

        result = brief_tool._run(paper_id="2409.05591")

        assert "Test Paper Title" in result
        assert "A summary of the paper" in result
        assert "machine learning" in result
        assert "Citations:** 100" in result
        assert "2024-01-15" in result
        assert "https://arxiv.org/pdf/2409.05591" in result
        assert "https://github.com/test/repo" in result

    def test_get_paper_brief_pmc(self, brief_tool, toolkit):
        """Test getting PMC paper brief."""
        mock_result = {
            "title": "PMC Paper Title",
            "tldr": "PMC summary",
            "keywords": [],
            "citations": 50,
        }
        toolkit._reader.pmc_head.return_value = mock_result

        result = brief_tool._run(paper_id="12345", source="pmc")

        assert "PMC Paper Title" in result
        toolkit._reader.pmc_head.assert_called_once_with("12345")

    def test_paper_not_found(self, brief_tool, toolkit):
        """Test paper not found handling."""
        toolkit._reader.brief.return_value = None

        result = brief_tool._run(paper_id="nonexistent")

        assert "not found" in result.lower()


# -----------------------------------------------------------------------------
# Paper Metadata Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivPaperMetadataTool:
    """Test DeepxivPaperMetadataTool functionality."""

    def test_tool_metadata(self, metadata_tool):
        """Test tool name and description."""
        assert metadata_tool.name == "deepxiv_paper_metadata"
        assert "metadata" in metadata_tool.description.lower()

    def test_get_metadata(self, metadata_tool, toolkit):
        """Test getting paper metadata."""
        mock_result = {
            "title": "Test Paper Title",
            "authors": [{"name": "John Doe"}, {"name": "Jane Smith"}],
            "categories": ["cs.AI", "cs.LG"],
            "publish_at": "2024-01-15",
            "token_count": 5000,
            "abstract": "This is the abstract.",
            "sections": {
                "Introduction": {"token_count": 500, "tldr": "Intro TLDR"},
                "Method": {"token_count": 1000, "tldr": "Method TLDR"},
            },
        }
        toolkit._reader.head.return_value = mock_result

        result = metadata_tool._run(paper_id="2409.05591")

        assert "Test Paper Title" in result
        assert "John Doe" in result
        assert "cs.AI" in result
        assert "5,000" in result  # formatted token count
        assert "This is the abstract" in result
        assert "Introduction" in result
        assert "500 tokens" in result
        assert "Intro TLDR" in result

    def test_get_metadata_pmc(self, metadata_tool, toolkit):
        """Test getting PMC paper metadata."""
        mock_result = {
            "title": "PMC Paper",
            "authors": [],
            "categories": [],
            "abstract": "PMC abstract",
            "sections": {},
        }
        toolkit._reader.pmc_head.return_value = mock_result

        result = metadata_tool._run(paper_id="12345", source="pmc")

        assert "PMC Paper" in result
        toolkit._reader.pmc_head.assert_called_once_with("12345")

    def test_metadata_no_sections(self, metadata_tool, toolkit):
        """Test metadata with no sections."""
        mock_result = {
            "title": "Simple Paper",
            "authors": [],
            "categories": [],
            "abstract": "Simple abstract",
            "sections": {},
        }
        toolkit._reader.head.return_value = mock_result

        result = metadata_tool._run(paper_id="2409.05591")

        assert "Simple Paper" in result
        # Should not crash with empty sections

    def test_metadata_author_truncation(self, metadata_tool, toolkit):
        """Test author list truncation for more than 5 authors."""
        mock_result = {
            "title": "Many Authors Paper",
            "authors": [{"name": f"Author {i}"} for i in range(10)],
            "categories": [],
            "abstract": "Abstract",
            "sections": {},
        }
        toolkit._reader.head.return_value = mock_result

        result = metadata_tool._run(paper_id="2409.05591")

        assert "et al." in result

    def test_metadata_string_authors(self, metadata_tool, toolkit):
        """Test metadata when API returns authors as plain strings."""
        mock_result = {
            "title": "String Authors Paper",
            "authors": ["Alice Smith", "Bob Jones"],
            "categories": [],
            "abstract": "Abstract",
            "sections": {},
        }
        toolkit._reader.head.return_value = mock_result

        result = metadata_tool._run(paper_id="2409.05591")

        assert "**Authors:** Alice Smith, Bob Jones" in result


# -----------------------------------------------------------------------------
# Read Section Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivReadSectionTool:
    """Test DeepxivReadSectionTool functionality."""

    def test_tool_metadata(self, read_section_tool):
        """Test tool name and description."""
        assert read_section_tool.name == "deepxiv_read_section"
        assert "section" in read_section_tool.description.lower()

    def test_read_section(self, read_section_tool, toolkit):
        """Test reading a paper section."""
        toolkit._reader.section.return_value = "This is the section content."

        result = read_section_tool._run(paper_id="2409.05591", section_name="Introduction")

        assert "Introduction" in result
        assert "2409.05591" in result
        assert "This is the section content." in result
        toolkit._reader.section.assert_called_once_with("2409.05591", "Introduction")

    def test_read_section_pmc(self, read_section_tool, toolkit):
        """Test reading a PMC paper section."""
        toolkit._reader.pmc_section.return_value = "PMC section content."

        result = read_section_tool._run(paper_id="12345", section_name="Results", source="pmc")

        assert "PMC section content." in result
        toolkit._reader.pmc_section.assert_called_once_with("12345", "Results")

    def test_section_not_found(self, read_section_tool, toolkit):
        """Test section not found handling."""
        toolkit._reader.section.return_value = None

        result = read_section_tool._run(paper_id="2409.05591", section_name="NonExistent")

        assert "not found" in result.lower()


# -----------------------------------------------------------------------------
# Get Full Paper Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivGetFullPaperTool:
    """Test DeepxivGetFullPaperTool functionality."""

    def test_tool_metadata(self, full_paper_tool):
        """Test tool name and description."""
        assert full_paper_tool.name == "deepxiv_get_full_paper"
        assert "complete" in full_paper_tool.description.lower()

    def test_get_full_paper(self, full_paper_tool, toolkit):
        """Test getting full paper content."""
        toolkit._reader.raw.return_value = "Full paper content here."

        result = full_paper_tool._run(paper_id="2409.05591")

        assert "Full Paper: 2409.05591" in result
        assert "Full paper content here." in result
        toolkit._reader.raw.assert_called_once_with("2409.05591")

    def test_paper_not_found(self, full_paper_tool, toolkit):
        """Test paper not found handling."""
        toolkit._reader.raw.return_value = None

        result = full_paper_tool._run(paper_id="nonexistent")

        assert "not found" in result.lower()


# -----------------------------------------------------------------------------
# Trending Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivTrendingTool:
    """Test DeepxivTrendingTool functionality."""

    def test_tool_metadata(self, trending_tool):
        """Test tool name and description."""
        assert trending_tool.name == "deepxiv_trending"
        assert "trending" in trending_tool.description.lower()

    def test_get_trending(self, trending_tool, toolkit):
        """Test getting trending papers."""
        mock_result = {
            "papers": [
                {
                    "arxiv_id": "2409.05591",
                    "title": "Trending Paper",
                    "abstract": "This paper is trending.",
                    "score": 95.5,
                }
            ]
        }
        toolkit._reader.trending.return_value = mock_result

        result = trending_tool._run(days=7, limit=10)

        assert "Trending papers" in result
        assert "2409.05591" in result
        assert "Trending Paper" in result
        assert "95.5" in result
        toolkit._reader.trending.assert_called_once_with(days=7, limit=10)

    def test_no_trending_papers(self, trending_tool, toolkit):
        """Test no trending papers."""
        toolkit._reader.trending.return_value = {"papers": []}

        result = trending_tool._run()

        assert "No trending papers" in result

    def test_empty_result(self, trending_tool, toolkit):
        """Test empty result."""
        toolkit._reader.trending.return_value = None

        result = trending_tool._run()

        assert "No trending papers" in result


# -----------------------------------------------------------------------------
# Websearch Tool Tests
# -----------------------------------------------------------------------------


class TestDeepxivWebsearchTool:
    """Test DeepxivWebsearchTool functionality."""

    def test_tool_metadata(self, websearch_tool):
        """Test tool name and description."""
        assert websearch_tool.name == "deepxiv_websearch"
        assert "web" in websearch_tool.description.lower()

    def test_websearch(self, websearch_tool, toolkit):
        """Test web search."""
        mock_result = [
            {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
        ]
        toolkit._reader.websearch.return_value = mock_result

        result = websearch_tool._run(query="test query")

        assert "Web search results" in result
        assert "Result 1" in result
        assert "https://example.com/1" in result
        assert "Snippet 1" in result
        toolkit._reader.websearch.assert_called_once_with("test query")

    def test_websearch_dict_result(self, websearch_tool, toolkit):
        """Test web search with dict result format."""
        mock_result = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
            ]
        }
        toolkit._reader.websearch.return_value = mock_result

        result = websearch_tool._run(query="test")

        assert "Result 1" in result

    def test_websearch_no_results(self, websearch_tool, toolkit):
        """Test web search with no results."""
        toolkit._reader.websearch.return_value = []

        result = websearch_tool._run(query="test")

        assert "No web search results" in result

    def test_websearch_empty_result(self, websearch_tool, toolkit):
        """Test web search with empty result."""
        toolkit._reader.websearch.return_value = None

        result = websearch_tool._run(query="test")

        assert "No web search results" in result


# -----------------------------------------------------------------------------
# Error Handling Tests
# -----------------------------------------------------------------------------


class TestErrorHandling:
    """Test error handling via _safe_call decorator."""

    def test_safe_call_passes_through_result(self):
        """Test _safe_call passes through successful results."""

        @_safe_call
        def successful_func():
            return "success"

        assert successful_func() == "success"

    def test_safe_call_handles_generic_exception(self):
        """Test _safe_call handles generic exceptions."""

        @_safe_call
        def failing_func():
            raise ValueError("Something went wrong")

        result = failing_func()
        assert "Error" in result
        assert "Something went wrong" in result

    def test_safe_call_handles_import_error(self):
        """Test _safe_call when deepxiv_sdk not installed."""

        @_safe_call
        def failing_func():
            raise RuntimeError("SDK not available")

        result = failing_func()
        assert "Error" in result

    def test_safe_call_maps_authentication_error(self, search_tool):
        """Test _safe_call maps deepxiv_sdk.reader.AuthenticationError without traceback spam."""
        from deepxiv_sdk import AuthenticationError

        search_tool.toolkit.reader.search.side_effect = AuthenticationError(
            "Invalid or expired token. Run 'deepxiv config' to set a valid token."
        )

        result = search_tool._run(query="MoE papers", size=5)

        assert "Invalid DeepXiv token" in result
        assert "DEEPXIV_API_KEY" in result
        assert "DeepXiv operation failed" not in result

    def test_deepxiv_exception_message_for_auth(self):
        """Test auth errors use the dedicated user message."""
        from deepxiv_sdk import AuthenticationError

        msg = _deepxiv_exception_message(
            AuthenticationError("Invalid or expired token"),
        )
        assert "Invalid DeepXiv token" in msg


class TestResolveDeepxivToken:
    """Tests for token resolution."""

    def test_resolve_from_env_api_key(self, monkeypatch):
        """Test DEEPXIV_API_KEY env fallback."""
        monkeypatch.delenv("DEEPXIV_TOKEN", raising=False)
        monkeypatch.setenv("DEEPXIV_API_KEY", "env-token")
        assert resolve_deepxiv_token(None) == "env-token"

    def test_resolve_from_env_token(self, monkeypatch):
        """Test DEEPXIV_TOKEN env fallback when API key unset."""
        monkeypatch.delenv("DEEPXIV_API_KEY", raising=False)
        monkeypatch.setenv("DEEPXIV_TOKEN", "token-env")
        assert resolve_deepxiv_token(None) == "token-env"

    def test_resolve_api_key_precedence_over_token(self, monkeypatch):
        """DEEPXIV_API_KEY wins when both env vars are set."""
        monkeypatch.setenv("DEEPXIV_API_KEY", "api-key")
        monkeypatch.setenv("DEEPXIV_TOKEN", "other-token")
        assert resolve_deepxiv_token(None) == "api-key"

    def test_resolve_env_placeholder(self, monkeypatch):
        """Test ${DEEPXIV_API_KEY} config placeholder."""
        monkeypatch.setenv("DEEPXIV_API_KEY", "from-env")
        assert resolve_deepxiv_token("${DEEPXIV_API_KEY}") == "from-env"

    def test_resolve_env_placeholder_token(self, monkeypatch):
        """Test ${DEEPXIV_TOKEN} config placeholder."""
        monkeypatch.delenv("DEEPXIV_API_KEY", raising=False)
        monkeypatch.setenv("DEEPXIV_TOKEN", "from-token-env")
        assert resolve_deepxiv_token("${DEEPXIV_TOKEN}") == "from-token-env"


# -----------------------------------------------------------------------------
# Plugin Tests
# -----------------------------------------------------------------------------


class TestDeepxivPlugin:
    """Test DeepxivPlugin functionality."""

    @pytest.fixture
    def mock_context(self):
        """Create mock plugin context."""
        context = MagicMock()
        context.soothe_config = None
        context.logger = MagicMock()
        return context

    @pytest.fixture
    def mock_context_with_config(self):
        """Create mock plugin context with config."""
        context = MagicMock()
        config = MagicMock()
        deepxiv_config = MagicMock()
        deepxiv_config.token = "config_token"
        deepxiv_config.timeout = 45
        deepxiv_config.max_retries = 5
        config.tools.deepxiv = deepxiv_config
        context.soothe_config = config
        context.logger = MagicMock()
        return context

    async def test_plugin_loads_with_config(self, mock_context_with_config):
        """Test plugin loads tools with config."""
        plugin = DeepxivPlugin()

        with patch.object(DeepxivToolkit, "__init__", return_value=None):
            mock_toolkit = MagicMock()
            mock_toolkit.get_tools.return_value = [MagicMock()]

            with patch.object(DeepxivToolkit, "get_tools", return_value=[MagicMock()]):
                await plugin.on_load(mock_context_with_config)

        assert len(plugin.get_tools()) > 0
        mock_context_with_config.logger.info.assert_called()

    async def test_plugin_loads_without_config(self, mock_context):
        """Test plugin loads tools without config (uses env var)."""
        plugin = DeepxivPlugin()

        with patch.dict("os.environ", {"DEEPXIV_API_KEY": "env_token"}):
            with patch.object(DeepxivToolkit, "__init__", return_value=None):
                with patch.object(DeepxivToolkit, "get_tools", return_value=[MagicMock()]):
                    await plugin.on_load(mock_context)

        assert len(plugin.get_tools()) > 0

    async def test_plugin_handles_missing_sdk(self, mock_context):
        """Test plugin handles missing deepxiv_sdk gracefully."""
        plugin = DeepxivPlugin()

        with patch("soothe_nano.toolkits.deepxiv.DeepxivToolkit") as mock_toolkit_class:
            mock_toolkit_class.side_effect = ImportError("No module named 'deepxiv_sdk'")
            await plugin.on_load(mock_context)

        assert plugin.get_tools() == []
        mock_context.logger.warning.assert_called()

    def test_get_tools_returns_list(self):
        """Test get_tools returns a list."""
        plugin = DeepxivPlugin()
        assert isinstance(plugin.get_tools(), list)


# -----------------------------------------------------------------------------
# Async Tests
# -----------------------------------------------------------------------------


class TestAsyncExecution:
    """Test async execution paths."""

    async def test_search_async(self, search_tool, toolkit):
        """Test async search execution."""
        toolkit._reader.search.return_value = {"result": [], "total_count": 0}

        result = await search_tool._arun(query="test")

        assert "No papers found" in result

    async def test_brief_async(self, brief_tool, toolkit):
        """Test async brief execution."""
        toolkit._reader.brief.return_value = {"title": "Test", "tldr": "TLDR"}

        result = await brief_tool._arun(paper_id="2409.05591")

        assert "Test" in result

    async def test_metadata_async(self, metadata_tool, toolkit):
        """Test async metadata execution."""
        toolkit._reader.head.return_value = {
            "title": "Test",
            "abstract": "Abstract",
            "sections": {},
        }

        result = await metadata_tool._arun(paper_id="2409.05591")

        assert "Test" in result

    async def test_read_section_async(self, read_section_tool, toolkit):
        """Test async read section execution."""
        toolkit._reader.section.return_value = "Content"

        result = await read_section_tool._arun(paper_id="2409.05591", section_name="Intro")

        assert "Content" in result

    async def test_full_paper_async(self, full_paper_tool, toolkit):
        """Test async full paper execution."""
        toolkit._reader.raw.return_value = "Full content"

        result = await full_paper_tool._arun(paper_id="2409.05591")

        assert "Full content" in result

    async def test_trending_async(self, trending_tool, toolkit):
        """Test async trending execution."""
        toolkit._reader.trending.return_value = {"papers": []}

        result = await trending_tool._arun()

        assert "No trending" in result

    async def test_websearch_async(self, websearch_tool, toolkit):
        """Test async websearch execution."""
        toolkit._reader.websearch.return_value = []

        result = await websearch_tool._arun(query="test")

        assert "No web search" in result
