"""Public URL content extraction via wizsearch crawl."""

from __future__ import annotations

import logging
import re
from typing import Any

from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_CAPABILITY_DESCRIPTION = (
    "Read and extract the main text content from a specific public HTTP or HTTPS URL."
)

_URL_PATTERN = re.compile(r"https?://[^\s\])>\"']+")


class UrlCrawlSource:
    """Headless page crawl for explicit URLs (WizsearchCrawlTool)."""

    capability_id: CapabilityId = "url_crawl"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._crawl_tool: Any | None = None

    def _ensure_tool(self) -> None:
        if self._crawl_tool is not None:
            return
        try:
            from soothe.toolkits.wizsearch import WizsearchCrawlTool

            self._crawl_tool = WizsearchCrawlTool(config={})
        except ImportError:
            logger.debug("WizsearchCrawlTool not available", exc_info=True)

    @property
    def name(self) -> str:
        return "url_crawl"

    @property
    def source_type(self) -> SourceType:
        return "url"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        self._ensure_tool()
        if not self._crawl_tool:
            return []

        urls = _URL_PATTERN.findall(query)
        if not urls:
            return []

        results: list[SourceResult] = []
        for url in urls[:2]:
            try:
                raw = await self._crawl_tool._arun(url=url)
                if raw and not raw.startswith("Error"):
                    results.append(
                        SourceResult(
                            content=raw[:5000],
                            source_ref=url,
                            source_name="url_crawl",
                            metadata={"url": url},
                        )
                    )
            except Exception:
                logger.debug("URL crawl failed for: %s", url, exc_info=True)
        return results
