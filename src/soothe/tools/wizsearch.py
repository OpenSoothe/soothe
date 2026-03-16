"""Wizsearch-powered web search and page crawling tools.

These tools expose multi-engine search and web page crawling through the
optional ``wizsearch`` package.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_core.tools import BaseTool
from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Awaitable

try:
    from wizsearch import PageCrawler, WizSearch, WizSearchConfig

    WIZSEARCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    PageCrawler = None
    WizSearch = None
    WizSearchConfig = None
    WIZSEARCH_AVAILABLE = False


def _require_wizsearch() -> None:
    """Ensure optional wizsearch dependency is available."""
    if not WIZSEARCH_AVAILABLE:
        msg = "wizsearch package is not installed. Install it with `pip install soothe[wizsearch]`."
        raise ImportError(msg)


def _normalize_engines(engines: list[str] | str | None) -> list[str] | None:
    """Normalize engine list input from list or comma-separated string."""
    if engines is None:
        return None
    if isinstance(engines, list):
        normalized = [str(engine).strip() for engine in engines if str(engine).strip()]
        return normalized or None
    if isinstance(engines, str):
        normalized = [part.strip() for part in engines.split(",") if part.strip()]
        return normalized or None
    return None


def _to_serializable_sources(result: object) -> list[dict[str, object]]:
    """Map wizsearch sources to plain dictionaries."""
    raw_sources = getattr(result, "sources", []) or []
    return [
        {
            "title": getattr(source, "title", ""),
            "url": getattr(source, "url", ""),
            "content": getattr(source, "content", ""),
        }
        for source in raw_sources
    ]


_T = TypeVar("_T")


def _run_coro(coro: Awaitable[_T]) -> _T:
    """Run an async coroutine from sync tool entrypoint."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        msg = "Cannot run synchronous tool method inside an active asyncio event loop. Use async invocation instead."
        raise RuntimeError(msg)
    return loop.run_until_complete(coro)


def _maybe_apply_tavily_key() -> None:
    """Backfill TAVILY_API_KEY from alternate env name when present."""
    if os.environ.get("TAVILY_API_KEY"):
        return
    alt = os.environ.get("WIZSEARCH_TAVILY_API_KEY")
    if alt:
        os.environ["TAVILY_API_KEY"] = alt


class WizsearchSearchTool(BaseTool):
    """Multi-engine web search tool powered by wizsearch."""

    name: str = "wizsearch_search"
    description: str = (
        "Search the web with multiple engines using wizsearch. "
        "Inputs: `query` and optional `engines` (list or comma-separated string), "
        "`max_results_per_engine` (default: 10), and `timeout` seconds (default: 30). "
        "Returns query, answer, sources, response_time, and metadata."
    )
    default_max_results_per_engine: int = Field(default=10)
    default_timeout: int = Field(default=30)
    default_engines: list[str] = Field(default_factory=lambda: ["tavily"])
    config: dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data: Any) -> None:
        """Initialize wizsearch search tool with optional config override.

        Args:
            **data: Tool configuration, including 'config' dict with
                'default_engines', 'max_results_per_engine', 'timeout', etc.
        """
        super().__init__(**data)
        # Override defaults from config if provided
        if self.config:
            if "default_engines" in self.config:
                self.default_engines = self.config["default_engines"]
            if "max_results_per_engine" in self.config:
                self.default_max_results_per_engine = self.config["max_results_per_engine"]
            if "timeout" in self.config:
                self.default_timeout = self.config["timeout"]

    def _build_result_payload(self, result: object) -> dict[str, object]:
        """Build a stable JSON-serializable output payload."""
        return {
            "query": getattr(result, "query", ""),
            "answer": getattr(result, "answer", None),
            "sources": _to_serializable_sources(result),
            "response_time": getattr(result, "response_time", None),
            "metadata": getattr(result, "metadata", None),
        }

    async def _perform_search(
        self,
        query: str,
        engines: list[str] | str | None = None,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, object]:
        _require_wizsearch()
        _maybe_apply_tavily_key()

        config_kwargs: dict[str, object] = {
            "max_results_per_engine": max_results_per_engine or self.default_max_results_per_engine,
            "timeout": timeout_seconds or self.default_timeout,
            "fail_silently": True,
        }
        normalized = _normalize_engines(engines) or self.default_engines
        config_kwargs["enabled_engines"] = normalized

        searcher = WizSearch(config=WizSearchConfig(**config_kwargs))
        result = await searcher.search(query=query)
        return self._build_result_payload(result)

    def _run(
        self,
        query: str,
        engines: list[str] | str | None = None,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, object]:
        return _run_coro(
            self._perform_search(
                query=query,
                engines=engines,
                max_results_per_engine=max_results_per_engine,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _arun(
        self,
        query: str,
        engines: list[str] | str | None = None,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, object]:
        return await self._perform_search(
            query=query,
            engines=engines,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )


class WizsearchCrawlPageTool(BaseTool):
    """Web page crawler tool powered by wizsearch.

    Note: The crawler runs in headless mode by default (BrowserConfig default).
    This is not configurable through this tool interface as wizsearch's PageCrawler
    doesn't expose the headless parameter.
    """

    name: str = "wizsearch_crawl_page"
    description: str = (
        "Crawl and extract web page content using wizsearch (runs in headless mode). "
        "Inputs: `url` and optional `content_format` ('markdown', 'html', 'text') "
        "and `only_text` (default: false). Returns extracted content and metadata."
    )
    default_content_format: str = Field(default="markdown")
    config: dict[str, Any] = Field(default_factory=dict)

    async def _perform_crawl(
        self,
        url: str,
        content_format: str | None = None,
        *,
        only_text: bool = False,
    ) -> dict[str, object]:
        _require_wizsearch()
        selected_format = (content_format or self.default_content_format).strip().lower()
        if selected_format not in {"markdown", "html", "text"}:
            selected_format = self.default_content_format

        # PageCrawler runs in headless mode by default (BrowserConfig default)
        crawler = PageCrawler(
            url=url,
            content_format=selected_format,
            only_text=only_text,
        )
        content = await crawler.crawl()
        return {
            "url": url,
            "content_format": selected_format,
            "only_text": only_text,
            "headless": True,  # Always true - wizsearch default
            "content": content or "",
            "content_length": len(content or ""),
        }

    def _run(
        self,
        url: str,
        content_format: str | None = None,
        *,
        only_text: bool = False,
    ) -> dict[str, object]:
        return _run_coro(
            self._perform_crawl(
                url=url,
                content_format=content_format,
                only_text=only_text,
            )
        )

    async def _arun(
        self,
        url: str,
        content_format: str | None = None,
        *,
        only_text: bool = False,
    ) -> dict[str, object]:
        return await self._perform_crawl(
            url=url,
            content_format=content_format,
            only_text=only_text,
        )


def create_wizsearch_tools(config: dict[str, Any] | None = None) -> list[BaseTool]:
    """Create wizsearch tool instances.

    Args:
        config: Optional configuration dict with keys:
            - default_engines: List of default search engines
            - max_results_per_engine: Max results per engine
            - timeout: Request timeout in seconds
            - headless: Run browser crawler in headless mode

    Returns:
        List containing wizsearch search and crawl tools.
    """
    config = config or {}
    return [
        WizsearchSearchTool(config=config),
        WizsearchCrawlPageTool(config=config),
    ]
