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

import inspect
import logging
import os
from functools import wraps
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from soothe_nano.config.env import _ENV_VAR_RE, _resolve_env

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 100
_auth_failure_logged = False
_DEEPXIV_TOKEN_ENV_VARS = ("DEEPXIV_API_KEY", "DEEPXIV_TOKEN")
_DEEPXIV_TOKEN_ENV_HINT = "DEEPXIV_API_KEY or DEEPXIV_TOKEN"


def _deepxiv_env_token() -> str | None:
    """Read token from ``DEEPXIV_API_KEY`` or ``DEEPXIV_TOKEN`` (first non-empty wins)."""
    for name in _DEEPXIV_TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def resolve_deepxiv_token(token: str | None) -> str | None:
    """Resolve DeepXiv API token from config value or env (``DEEPXIV_API_KEY`` / ``DEEPXIV_TOKEN``)."""
    if token:
        text = str(token).strip()
        if text:
            resolved = _resolve_env(text)
            if not _ENV_VAR_RE.match(resolved):
                return resolved
    return _deepxiv_env_token()


def _deepxiv_exception_kind(exc: Exception) -> str:
    """Classify a DeepXiv SDK exception for logging and user messages."""
    try:
        from deepxiv_sdk import (
            APIError,
            AuthenticationError,
            NotFoundError,
            RateLimitError,
        )
    except ImportError:
        name = type(exc).__name__
        if name == "AuthenticationError":
            return "auth_error"
        if name == "RateLimitError":
            return "rate_limit"
        if name == "NotFoundError":
            return "not_found"
        if name == "APIError":
            return "api_error"
        return "unknown"

    if isinstance(exc, AuthenticationError):
        return "auth_error"
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, NotFoundError):
        return "not_found"
    if isinstance(exc, APIError):
        return "api_error"
    return "unknown"


def _deepxiv_exception_message(exc: Exception) -> str:
    """Map a DeepXiv SDK exception to a user-facing tool result string."""
    kind = _deepxiv_exception_kind(exc)
    if kind == "auth_error":
        return (
            f"Error: Invalid DeepXiv token. "
            f"Set {_DEEPXIV_TOKEN_ENV_HINT} or register at https://data.rag.ac.cn"
        )
    if kind == "rate_limit":
        return (
            "Error: Daily API limit reached. Register at https://data.rag.ac.cn for higher limits."
        )
    if kind == "not_found":
        return "Error: Paper not found. Check the ID and try again."
    if kind == "api_error":
        return f"Error: DeepXiv API error - {exc}"
    return f"Error: DeepXiv operation failed - {exc}"


def _log_deepxiv_exception(tool_name: str, preview: str, exc: Exception) -> None:
    """Log SDK failures without noisy tracebacks for expected API errors."""
    global _auth_failure_logged
    kind = _deepxiv_exception_kind(exc)
    if kind == "auth_error":
        if not _auth_failure_logged:
            logger.warning(
                "[DeepXiv] API authentication failed (invalid or expired token). "
                "Set %s or register at https://data.rag.ac.cn",
                _DEEPXIV_TOKEN_ENV_HINT,
            )
            _auth_failure_logged = True
        logger.info("[DeepXiv] %s %s status=auth_error", tool_name, preview)
        return
    if kind == "rate_limit":
        logger.warning("[DeepXiv] %s %s status=rate_limit error=%s", tool_name, preview, exc)
        return
    if kind in ("not_found", "api_error"):
        logger.warning("[DeepXiv] %s %s status=%s error=%s", tool_name, preview, kind, exc)
        return
    logger.warning(
        "[DeepXiv] %s %s status=exception error=%s",
        tool_name,
        preview,
        exc,
        exc_info=True,
    )


def _preview(value: object, *, max_len: int = _PREVIEW_LEN) -> str:
    text = " ".join(str(value).split())
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def _author_display_name(author: object) -> str:
    """Extract display name from a DeepXiv author entry (dict or plain string)."""
    if isinstance(author, str):
        return author.strip()
    if isinstance(author, dict):
        name = author.get("name")
        if name is not None:
            return str(name).strip()
    return ""


def _format_author_names(authors: list[object], *, limit: int) -> str:
    """Join author names for display, with optional 'et al.' when truncated."""
    if not authors:
        return ""
    names = [n for n in (_author_display_name(a) for a in authors[:limit]) if n]
    if not names:
        return ""
    text = ", ".join(names)
    if len(authors) > limit:
        text += " et al."
    return text


def _format_call_preview(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    """Build a short log fragment from tool call arguments."""
    parts: list[str] = []
    if len(args) > 1:
        parts.append(f"arg0={_preview(args[1])}")
    for key in ("query", "paper_id", "section_name", "source", "size", "days", "limit"):
        if key in kwargs and kwargs[key] is not None:
            parts.append(f"{key}={_preview(kwargs[key])}")
    return " ".join(parts) if parts else "(no args)"


def _log_deepxiv_done(tool_name: str, preview: str, result: str) -> None:
    """Log tool completion outcome (mirrors wizsearch engine status visibility)."""
    if result.startswith("Error"):
        logger.warning(
            "[DeepXiv] %s %s status=error message=%s",
            tool_name,
            preview,
            _preview(result, max_len=200),
        )
    elif result.startswith("No ") or "not found" in result.lower():
        logger.info("[DeepXiv] %s %s status=no_results", tool_name, preview)
    else:
        logger.info(
            "[DeepXiv] %s %s status=success output_chars=%d",
            tool_name,
            preview,
            len(result),
        )


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


def _safe_call(tool_func):  # type: ignore[no-untyped-def]
    """Decorator to convert DeepXiv SDK exceptions to user-friendly messages."""

    @wraps(tool_func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        params = list(inspect.signature(tool_func).parameters)
        bound_method = bool(params and params[0] == "self" and args)
        if bound_method:
            self, call_args = args[0], args[1:]
            tool_name = getattr(self, "name", tool_func.__qualname__)
            preview = _format_call_preview(call_args, kwargs)
        else:
            tool_name = tool_func.__qualname__
            preview = _format_call_preview(args, kwargs)

        logger.info("[DeepXiv] %s start %s", tool_name, preview)
        try:
            if bound_method:
                result = tool_func(self, *call_args, **kwargs)
            else:
                result = tool_func(*args, **kwargs)
        except Exception as e:
            _log_deepxiv_exception(tool_name, preview, e)
            result = _deepxiv_exception_message(e)
            if _deepxiv_exception_kind(e) != "auth_error" and (
                tool_name != "deepxiv_search" or result.startswith("Error")
            ):
                _log_deepxiv_done(tool_name, preview, result)
            return result

        if isinstance(result, str):
            # deepxiv_search logs structured hit counts in _run
            if tool_name != "deepxiv_search":
                _log_deepxiv_done(tool_name, preview, result)
            elif result.startswith("Error") or result.startswith("No "):
                _log_deepxiv_done(tool_name, preview, result)
        return result

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
        self.token = resolve_deepxiv_token(token)
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
                logger.info(
                    "[DeepXiv] Reader initialized (timeout=%ss, max_retries=%d, token=%s)",
                    self.timeout,
                    self.max_retries,
                    "set" if self.token else "anonymous",
                )
            except ImportError:
                logger.warning(
                    "[DeepXiv] deepxiv_sdk not installed; install/upgrade soothe for academic tools"
                )
                raise RuntimeError("deepxiv_sdk not installed. Install with: pip install -U soothe")
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
        super().__init__(toolkit=toolkit, **data)

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
            logger.info(
                "[DeepXiv] deepxiv_search query=%r status=no_results total=%d",
                query,
                total,
            )
            return "No papers found matching your query."

        logger.info(
            "[DeepXiv] deepxiv_search query=%r status=success papers=%d total=%d",
            _preview(query, max_len=80),
            len(papers),
            total,
        )
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
            author_names = _format_author_names(authors, limit=3)
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
        super().__init__(toolkit=toolkit, **data)

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
        super().__init__(toolkit=toolkit, **data)

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
        author_names = _format_author_names(authors, limit=5)
        if author_names:
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
        super().__init__(toolkit=toolkit, **data)

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
        super().__init__(toolkit=toolkit, **data)

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
        super().__init__(toolkit=toolkit, **data)

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
        super().__init__(toolkit=toolkit, **data)

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
        # Get config from soothe_config
        sc = getattr(context, "soothe_config", None)
        token: str | None = None
        timeout: int = 60
        max_retries: int = 3

        if sc and hasattr(sc, "tools"):
            deepxiv_config = getattr(sc.tools, "deepxiv", None)
            if deepxiv_config:
                token = getattr(deepxiv_config, "token", None)
                timeout = getattr(deepxiv_config, "timeout", 60)
                max_retries = getattr(deepxiv_config, "max_retries", 3)

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
