"""DeepXiv toolkit -- academic paper search and progressive reading.

Provides access to arXiv, bioRxiv, medRxiv, and PubMed Central papers with
AI-generated TLDRs and section-level access for token-efficient reading.

Tools:
- deepxiv_search: Semantic paper search
- deepxiv_paper_brief: Quick summary (TLDR, keywords, citations)
- deepxiv_paper_metadata: Paper structure overview
- deepxiv_read_section: Read specific sections
- deepxiv_get_full_paper: Complete paper content
- deepxiv_trending: Trending papers by social signals
- deepxiv_websearch: Web search (higher token cost)
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


def _safe_call(tool_func):  # type: ignore[no-untyped-def]
    """Decorator to convert DeepXiv SDK exceptions to user-friendly messages."""

    @wraps(tool_func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return tool_func(*args, **kwargs)
        except Exception as e:
            # Handle DeepXiv SDK exceptions if available
            try:
                from deepxiv_sdk.exceptions import (
                    APIError,
                    AuthenticationError,
                    NotFoundError,
                    RateLimitError,
                )

                if isinstance(e, AuthenticationError):
                    return (
                        "Error: Invalid DeepXiv token. "
                        "Configure DEEPXIV_API_KEY or get one at data.rag.ac.cn"
                    )
                if isinstance(e, RateLimitError):
                    return (
                        "Error: Daily API limit reached. "
                        "Register at data.rag.ac.cn for higher limits."
                    )
                if isinstance(e, NotFoundError):
                    return "Error: Paper not found. Check the ID and try again."
                if isinstance(e, APIError):
                    return f"Error: DeepXiv API error - {e}"
            except ImportError:
                pass  # deepxiv_sdk not installed
            return f"Error: DeepXiv operation failed - {e}"

    return wrapper


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------


class DeepxivSearchInput(BaseModel):
    """Input for deepxiv_search tool."""

    query: str = Field(description="Search query for papers")
    size: int = Field(default=10, description="Number of results to return (max 50)")
    source: str | None = Field(
        default=None,
        description="Filter by source: 'arxiv', 'biorxiv', 'medrxiv', 'pmc', or None for all",
    )
    categories: list[str] | None = Field(
        default=None, description="Filter by categories (e.g., ['cs.AI', 'cs.CL'])"
    )
    authors: list[str] | None = Field(default=None, description="Filter by authors")
    organizations: list[str] | None = Field(default=None, description="Filter by organizations")
    date_from: str | None = Field(default=None, description="Start date filter (YYYY-MM-DD format)")
    date_to: str | None = Field(default=None, description="End date filter (YYYY-MM-DD format)")
    min_citation: int | None = Field(default=None, description="Minimum citation count")


class DeepxivPaperBriefInput(BaseModel):
    """Input for deepxiv_paper_brief tool."""

    paper_id: str = Field(
        description="Paper ID (e.g., '2409.05591' for arXiv, or PMC ID for PubMed Central)"
    )
    source: str = Field(
        default="arxiv", description="Source type: 'arxiv', 'biorxiv', 'medrxiv', or 'pmc'"
    )


class DeepxivPaperMetadataInput(BaseModel):
    """Input for deepxiv_paper_metadata tool."""

    paper_id: str = Field(
        description="Paper ID (e.g., '2409.05591' for arXiv, or PMC ID for PubMed Central)"
    )
    source: str = Field(
        default="arxiv", description="Source type: 'arxiv', 'biorxiv', 'medrxiv', or 'pmc'"
    )


class DeepxivReadSectionInput(BaseModel):
    """Input for deepxiv_read_section tool."""

    paper_id: str = Field(
        description="Paper ID (e.g., '2409.05591' for arXiv, or PMC ID for PubMed Central)"
    )
    section_name: str = Field(description="Section name (e.g., 'Introduction', 'Method')")
    source: str = Field(
        default="arxiv", description="Source type: 'arxiv', 'biorxiv', 'medrxiv', or 'pmc'"
    )


class DeepxivGetFullPaperInput(BaseModel):
    """Input for deepxiv_get_full_paper tool."""

    paper_id: str = Field(
        description="Paper ID (e.g., '2409.05591' for arXiv, or PMC ID for PubMed Central)"
    )
    source: str = Field(
        default="arxiv", description="Source type: 'arxiv', 'biorxiv', 'medrxiv', or 'pmc'"
    )


class DeepxivTrendingInput(BaseModel):
    """Input for deepxiv_trending tool."""

    days: int = Field(default=7, description="Number of days to look back")
    limit: int = Field(default=10, description="Number of papers to return")


class DeepxivWebsearchInput(BaseModel):
    """Input for deepxiv_websearch tool."""

    query: str = Field(description="Web search query")


# ---------------------------------------------------------------------------
# Toolkit Class
# ---------------------------------------------------------------------------


class DeepxivToolkit:
    """Toolkit for DeepXiv academic paper operations.

    Manages shared DeepXiv Reader instance with lazy initialization.
    Supports token-based access with free tier (1,000 req/day auto-register)
    and registered tier (10,000 req/day).

    Args:
        token: API token (optional, auto-registers if None)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        """Initialize the DeepXiv toolkit."""
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self._reader: Any | None = None

    @property
    def reader(self) -> Any:
        """Lazy-loaded DeepXiv Reader instance."""
        if self._reader is None:
            try:
                from deepxiv_sdk import Reader

                self._reader = Reader(
                    token=self.token,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                )
            except ImportError:
                raise RuntimeError(
                    "deepxiv_sdk not installed. Install with: pip install 'soothe[research]'"
                )
        return self._reader

    def get_tools(self) -> list[BaseTool]:
        """Return all DeepXiv tools."""
        return [
            DeepxivSearchTool(toolkit=self),
            DeepxivPaperBriefTool(toolkit=self),
            DeepxivPaperMetadataTool(toolkit=self),
            DeepxivReadSectionTool(toolkit=self),
            DeepxivGetFullPaperTool(toolkit=self),
            DeepxivTrendingTool(toolkit=self),
            DeepxivWebsearchTool(toolkit=self),
        ]


# ---------------------------------------------------------------------------
# Tool Classes
# ---------------------------------------------------------------------------


class DeepxivSearchTool(BaseTool):
    """Search for academic papers using DeepXiv semantic search."""

    name: str = "deepxiv_search"
    description: str = (
        "Search for academic papers across arXiv, bioRxiv, medRxiv, and PubMed Central. "
        "Uses semantic search to find relevant papers. "
        "Returns: paper ID, title, abstract, score, citation count, authors, categories. "
        "Use this FIRST to find papers on a topic. "
        "Cost: 1 API token per request. "
        "Parameters: query (required), size (default 10), source (optional filter), "
        "categories (optional), authors (optional), date_from/date_to (optional), "
        "min_citation (optional)."
    )
    args_schema: type[BaseModel] = DeepxivSearchInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        query: str,
        size: int = 10,
        source: str | None = None,
        categories: list[str] | None = None,
        authors: list[str] | None = None,
        organizations: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_citation: int | None = None,
    ) -> str:
        """Execute paper search."""
        reader = self.toolkit.reader

        # Build search parameters
        params: dict[str, Any] = {"query": query, "size": min(size, 50)}
        if source:
            params["source"] = source
        if categories:
            params["categories"] = categories
        if authors:
            params["authors"] = authors
        if organizations:
            params["organizations"] = organizations
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if min_citation is not None:
            params["min_citation"] = min_citation

        result = reader.search(**params)

        if not result or "result" not in result:
            return "No papers found matching your query."

        papers = result["result"]
        total = result.get("total_count", len(papers))

        if not papers:
            return "No papers found matching your query."

        lines = [f"Found {total} papers (showing {len(papers)}):\n"]
        for paper in papers:
            paper_id = (
                paper.get("arxiv_id")
                or paper.get("biorxiv_id")
                or paper.get("medrxiv_id")
                or paper.get("pmc_id")
                or "unknown"
            )
            title = paper.get("title", "No title")
            abstract = paper.get("abstract", "No abstract")[:300]
            score = paper.get("score", 0)
            citations = paper.get("citation_count", 0)
            authors = paper.get("authors", [])
            author_names = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_names += " et al."
            categories = paper.get("categories", [])
            cat_str = ", ".join(categories[:3]) if categories else ""

            lines.append(f"\n**{paper_id}** - {title}")
            lines.append(f"  Authors: {author_names}")
            lines.append(f"  Categories: {cat_str}")
            lines.append(f"  Citations: {citations} | Relevance: {score:.2f}")
            lines.append(f"  Abstract: {abstract}...")

        return "\n".join(lines)

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivPaperBriefTool(BaseTool):
    """Get a quick summary of an academic paper."""

    name: str = "deepxiv_paper_brief"
    description: str = (
        "Get a quick summary of an academic paper. "
        "Returns: title, AI-generated TLDR, keywords, citation count, GitHub link. "
        "Use this FIRST to decide if a paper is worth deeper reading. "
        "Cost: 1 API token per request. "
        "Parameters: paper_id (required) - e.g., '2409.05591', "
        "source (default 'arxiv') - 'arxiv', 'biorxiv', 'medrxiv', or 'pmc'."
    )
    args_schema: type[BaseModel] = DeepxivPaperBriefInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        paper_id: str,
        source: str = "arxiv",
    ) -> str:
        """Get paper brief."""
        reader = self.toolkit.reader

        if source.lower() == "pmc":
            # PMC uses different endpoint
            result = reader.pmc_head(paper_id)
        else:
            result = reader.brief(paper_id)

        if not result:
            return f"Paper '{paper_id}' not found."

        lines = [
            f"**{result.get('title', 'No title')}**",
            "",
            f"**TLDR:** {result.get('tldr', 'No summary available')}",
            "",
        ]

        keywords = result.get("keywords", [])
        if keywords:
            lines.append(f"**Keywords:** {', '.join(keywords)}")

        lines.append(f"**Citations:** {result.get('citations', 'N/A')}")

        publish_date = result.get("publish_at")
        if publish_date:
            lines.append(f"**Published:** {publish_date}")

        pdf_url = result.get("pdf_url")
        if pdf_url:
            lines.append(f"**PDF:** {pdf_url}")

        github_url = result.get("github_url")
        if github_url:
            lines.append(f"**Code:** {github_url}")

        return "\n".join(lines)

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivPaperMetadataTool(BaseTool):
    """Get paper metadata and structure overview."""

    name: str = "deepxiv_paper_metadata"
    description: str = (
        "Get paper metadata including authors, abstract, and section structure. "
        "Returns: title, authors, abstract, categories, publish date, "
        "token count, and available sections with token counts and TLDRs. "
        "Use this to understand paper structure before reading specific sections. "
        "Cost: 1 API token per request. "
        "Parameters: paper_id (required), source (default 'arxiv')."
    )
    args_schema: type[BaseModel] = DeepxivPaperMetadataInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        paper_id: str,
        source: str = "arxiv",
    ) -> str:
        """Get paper metadata."""
        reader = self.toolkit.reader

        if source.lower() == "pmc":
            result = reader.pmc_head(paper_id)
        else:
            result = reader.head(paper_id)

        if not result:
            return f"Paper '{paper_id}' not found."

        lines = [
            f"**{result.get('title', 'No title')}**",
            "",
        ]

        authors = result.get("authors", [])
        if authors:
            author_names = ", ".join(a.get("name", "") for a in authors[:5])
            if len(authors) > 5:
                author_names += " et al."
            lines.append(f"**Authors:** {author_names}")

        categories = result.get("categories", [])
        if categories:
            lines.append(f"**Categories:** {', '.join(categories)}")

        publish_at = result.get("publish_at")
        if publish_at:
            lines.append(f"**Published:** {publish_at}")

        token_count = result.get("token_count")
        if token_count:
            lines.append(f"**Total Tokens:** {token_count:,}")

        lines.append("")
        abstract = result.get("abstract", "No abstract available")
        lines.append(f"**Abstract:**\n{abstract}")
        lines.append("")

        sections = result.get("sections", {})
        if sections:
            lines.append("**Available Sections:**")
            for section_name, section_info in sections.items():
                if isinstance(section_info, dict):
                    sec_tokens = section_info.get("token_count", "?")
                    sec_tldr = section_info.get("tldr", "")
                    if sec_tldr:
                        lines.append(f"  - {section_name} ({sec_tokens} tokens): {sec_tldr}")
                    else:
                        lines.append(f"  - {section_name} ({sec_tokens} tokens)")
                else:
                    lines.append(f"  - {section_name}")

        return "\n".join(lines)

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivReadSectionTool(BaseTool):
    """Read a specific section of an academic paper."""

    name: str = "deepxiv_read_section"
    description: str = (
        "Read a specific section of an academic paper. "
        "Returns: Section content in markdown format. "
        "Use this to read only relevant sections (token-efficient). "
        "First use deepxiv_paper_metadata to see available sections. "
        "Cost: 1 API token per request. "
        "Parameters: paper_id (required), section_name (required), source (default 'arxiv')."
    )
    args_schema: type[BaseModel] = DeepxivReadSectionInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        paper_id: str,
        section_name: str,
        source: str = "arxiv",
    ) -> str:
        """Read paper section."""
        reader = self.toolkit.reader

        if source.lower() == "pmc":
            content = reader.pmc_section(paper_id, section_name)
        else:
            content = reader.section(paper_id, section_name)

        if not content:
            return f"Section '{section_name}' not found in paper '{paper_id}'."

        header = f"**{section_name}** from {paper_id}\n{'=' * 50}\n\n"
        return header + content

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivGetFullPaperTool(BaseTool):
    """Get the full content of an academic paper."""

    name: str = "deepxiv_get_full_paper"
    description: str = (
        "Get the complete content of an academic paper in markdown format. "
        "WARNING: This can be very long (thousands to tens of thousands of tokens). "
        "Use deepxiv_read_section for targeted reading instead when possible. "
        "Cost: 1 API token per request (but high token count for content). "
        "Parameters: paper_id (required), source (default 'arxiv')."
    )
    args_schema: type[BaseModel] = DeepxivGetFullPaperInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        paper_id: str,
        source: str = "arxiv",
    ) -> str:
        """Get full paper content."""
        reader = self.toolkit.reader

        # Note: raw() returns full paper content
        content = reader.raw(paper_id)

        if not content:
            return f"Paper '{paper_id}' not found or content unavailable."

        header = f"**Full Paper: {paper_id}**\n{'=' * 50}\n\n"
        return header + content

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivTrendingTool(BaseTool):
    """Get trending papers based on social signals."""

    name: str = "deepxiv_trending"
    description: str = (
        "Get trending academic papers based on social signals (Twitter, Reddit, etc.). "
        "Returns: List of trending papers with engagement metrics. "
        "Use this to discover popular recent papers. "
        "Cost: 1 API token per request. "
        "Parameters: days (default 7), limit (default 10)."
    )
    args_schema: type[BaseModel] = DeepxivTrendingInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        days: int = 7,
        limit: int = 10,
    ) -> str:
        """Get trending papers."""
        reader = self.toolkit.reader

        result = reader.trending(days=days, limit=limit)

        if not result or "papers" not in result:
            return "No trending papers found."

        papers = result["papers"]
        if not papers:
            return "No trending papers found."

        lines = [f"Trending papers (last {days} days):\n"]
        for paper in papers:
            paper_id = (
                paper.get("arxiv_id")
                or paper.get("biorxiv_id")
                or paper.get("medrxiv_id")
                or "unknown"
            )
            title = paper.get("title", "No title")
            abstract = paper.get("abstract", "No abstract")[:250]
            score = paper.get("score", 0)

            lines.append(f"\n**{paper_id}** - {title}")
            lines.append(f"  Trend Score: {score:.2f}")
            lines.append(f"  Abstract: {abstract}...")

        return "\n".join(lines)

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


class DeepxivWebsearchTool(BaseTool):
    """Web search using DeepXiv (higher token cost)."""

    name: str = "deepxiv_websearch"
    description: str = (
        "Search the web using DeepXiv's web search capability. "
        "Returns: Search results with titles, URLs, and snippets. "
        "Use this for broader context beyond academic papers. "
        "WARNING: Higher token cost (20 tokens vs 1 for paper search). "
        "Cost: 20 API tokens per request. "
        "Parameters: query (required)."
    )
    args_schema: type[BaseModel] = DeepxivWebsearchInput

    toolkit: DeepxivToolkit = Field(exclude=True)

    def __init__(self, toolkit: DeepxivToolkit, **data: Any) -> None:
        """Initialize with toolkit reference."""
        super().__init__(**data)
        self.toolkit = toolkit

    @_safe_call
    def _run(
        self,
        query: str,
    ) -> str:
        """Execute web search."""
        reader = self.toolkit.reader

        result = reader.websearch(query)

        if not result:
            return "No web search results found."

        # Format depends on DeepXiv API response structure
        if isinstance(result, dict):
            results_list = result.get("results", result.get("result", []))
        elif isinstance(result, list):
            results_list = result
        else:
            return str(result)

        if not results_list:
            return "No web search results found."

        lines = [f"Web search results for '{query}':\n"]
        for item in results_list:
            if isinstance(item, dict):
                title = item.get("title", "No title")
                url = item.get("url", item.get("link", ""))
                snippet = item.get("snippet", item.get("content", "No description"))
                lines.append(f"\n**{title}**")
                if url:
                    lines.append(f"  URL: {url}")
                lines.append(f"  {snippet}")
            else:
                lines.append(f"\n{item}")

        return "\n".join(lines)

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution (runs sync)."""
        return self._run(**kwargs)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class DeepxivPlugin:
    """DeepXiv tools plugin for Soothe SDK.

    Provides academic paper search and reading capabilities via DeepXiv SDK.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with config.

        Args:
            context: Plugin context with config and logger.
        """
        import os

        # Get config from soothe_config
        sc = getattr(context, "soothe_config", None)
        token: str | None = None
        timeout: int = 60
        max_retries: int = 3

        if sc and hasattr(sc, "tools"):
            deepxiv_config = getattr(sc.tools, "deepxiv", None)
            if deepxiv_config:
                token = getattr(deepxiv_config, "token", None) or os.environ.get("DEEPXIV_API_KEY")
                timeout = getattr(deepxiv_config, "timeout", 60)
                max_retries = getattr(deepxiv_config, "max_retries", 3)

        # Fallback to environment variable
        if not token:
            token = os.environ.get("DEEPXIV_API_KEY")

        try:
            toolkit = DeepxivToolkit(
                token=token,
                timeout=timeout,
                max_retries=max_retries,
            )
            self._tools = toolkit.get_tools()
            context.logger.info(
                "Loaded %d DeepXiv tools (token=%s)",
                len(self._tools),
                "configured" if token else "auto-register",
            )
        except ImportError:
            context.logger.warning("deepxiv_sdk not installed, DeepXiv tools unavailable")
            self._tools = []

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of DeepXiv tool instances.
        """
        return self._tools
