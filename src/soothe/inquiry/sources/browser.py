"""Browser InformationSource wrapping the browser subagent."""

from __future__ import annotations

import logging
from typing import Any

from soothe.inquiry.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_URL_RELEVANCE_SCORE = 0.9
_MIN_BROWSER_SCORE = 0.02


class BrowserSource:
    """Information source backed by browser automation.

    Used for content that requires JavaScript rendering, form interaction,
    or login-protected pages. Falls back to HTTP crawling for simple
    URL extraction when a full browser session is overkill.

    Args:
        config: Optional Soothe config for browser subagent settings.
    """

    def __init__(self, config: Any | None = None) -> None:
        """Initialize the browser source with optional config."""
        self._config = config
        self._crawl_tool: Any | None = None

    def _ensure_tools(self) -> None:
        if self._crawl_tool is not None:
            return
        try:
            from soothe.tools._internal.wizsearch.crawl import WizsearchCrawlPageTool

            self._crawl_tool = WizsearchCrawlPageTool()
        except Exception:
            logger.debug("Crawl tool not available", exc_info=True)

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "browser"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "browser"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Extract content from URLs or JS-heavy pages.

        For queries containing URLs, crawls each URL.  For non-URL queries,
        this source is generally not the right choice (returns empty).

        Args:
            query: URL or description of content to extract.
            context: Current research context.

        Returns:
            List of SourceResult with page content.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        urls = self._extract_urls(query)
        if not urls and self._crawl_tool is None:
            return results

        if urls and self._crawl_tool:
            for url in urls[:3]:
                try:
                    raw = await self._crawl_tool._arun(url=url)
                    if raw and not raw.startswith("Error"):
                        results.append(
                            SourceResult(
                                content=raw[:5000],
                                source_ref=url,
                                source_name="browser",
                                metadata={"type": "page_crawl"},
                            )
                        )
                except Exception:
                    logger.debug("Failed to crawl URL: %s", url, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for URLs and interactive-content queries."""
        from soothe.inquiry.sources._scoring import _BROWSER_KEYWORDS, has_url, keyword_score

        if has_url(query):
            return _URL_RELEVANCE_SCORE

        score = keyword_score(query, _BROWSER_KEYWORDS, weight=0.2)
        return min(1.0, max(_MIN_BROWSER_SCORE, score))

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _extract_urls(query: str) -> list[str]:
        """Extract HTTP(S) URLs from the query string."""
        import re

        return re.findall(r"https?://\S+", query)
