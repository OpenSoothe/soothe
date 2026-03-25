"""Web page crawler tool powered by wizsearch."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.tools._internal.wizsearch._helpers import _require_wizsearch, _run_coro
from soothe.tools.web_search.events import (
    TOOL_WEBSEARCH_CRAWL_COMPLETED,
    TOOL_WEBSEARCH_CRAWL_FAILED,
    TOOL_WEBSEARCH_CRAWL_STARTED,
)
from soothe.utils.url_validation import validate_url

logger = logging.getLogger(__name__)


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
        from wizsearch import PageCrawler

        from soothe.utils.output_capture import capture_subagent_output
        from soothe.utils.progress import emit_progress

        _require_wizsearch()
        selected_format = (content_format or self.default_content_format).strip().lower()
        if selected_format not in {"markdown", "html", "text"}:
            selected_format = self.default_content_format

        validated_url, error = validate_url(url)
        if error:
            logger.warning("Invalid URL: %s", error)
            emit_progress(
                {
                    "type": TOOL_WEBSEARCH_CRAWL_FAILED,
                    "url": url,
                    "error": error,
                    "tool": "wizsearch_crawl_page",
                    "tool_group": "websearch",
                },
                logger,
            )
            return {
                "url": url,
                "content_format": selected_format,
                "only_text": only_text,
                "headless": True,
                "content": "",
                "content_length": 0,
                "error": error,
            }

        emit_progress(
            {
                "type": TOOL_WEBSEARCH_CRAWL_STARTED,
                "url": validated_url,
                "content_format": selected_format,
                "tool": "wizsearch_crawl_page",
                "tool_group": "websearch",
            },
            logger,
        )

        try:
            with capture_subagent_output("wizsearch", suppress=True):
                crawler = PageCrawler(
                    url=validated_url,
                    content_format=selected_format,
                    only_text=only_text,
                )
                content = await crawler.crawl()

            payload = {
                "url": validated_url,
                "content_format": selected_format,
                "only_text": only_text,
                "headless": True,
                "content": content or "",
                "content_length": len(content or ""),
            }

            emit_progress(
                {
                    "type": TOOL_WEBSEARCH_CRAWL_COMPLETED,
                    "url": validated_url,
                    "content_length": len(content or ""),
                    "tool": "wizsearch_crawl_page",
                    "tool_group": "websearch",
                },
                logger,
            )
        except Exception as exc:
            logger.exception("Crawl failed for %s", validated_url)

            error_str = str(exc).lower()
            if "timeout" in error_str:
                logger.warning("Crawl timed out - consider increasing timeout or checking network")
            elif "connection" in error_str:
                logger.warning("Connection failed - check URL accessibility and proxy settings")
            elif "javascript" in error_str or "render" in error_str:
                logger.warning("JavaScript rendering issue - page may require JS execution")

            emit_progress(
                {
                    "type": TOOL_WEBSEARCH_CRAWL_FAILED,
                    "url": validated_url,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "tool": "wizsearch_crawl_page",
                    "tool_group": "websearch",
                },
                logger,
            )
            return {
                "url": validated_url,
                "content_format": selected_format,
                "only_text": only_text,
                "headless": True,
                "content": "",
                "content_length": 0,
                "error": str(exc),
            }
        else:
            return payload

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
