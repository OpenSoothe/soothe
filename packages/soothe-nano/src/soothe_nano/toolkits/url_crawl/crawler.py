"""URL content extraction for research subagents."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel

from soothe_nano.toolkits.url_crawl.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://[^\s\])>\"']+")


class CrawlResult(BaseModel):
    """One crawled page."""

    url: str
    content: str = ""
    title: str | None = None
    success: bool = True
    error: str | None = None


def extract_urls(text: str, *, limit: int = 20) -> list[str]:
    """Extract HTTP(S) URLs from text."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text or ""):
        url = match.rstrip(".,;)")
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def urls_from_search_results(results: list[Any], *, limit: int = 10) -> list[str]:
    """Collect URLs from web search ``SourceResult`` metadata and refs."""
    urls: list[str] = []
    seen: set[str] = set()
    for result in results:
        meta = getattr(result, "metadata", None) or {}
        if isinstance(result, dict):
            meta = result.get("metadata") or {}
        candidates = [
            meta.get("url"),
            meta.get("link"),
            getattr(result, "source_ref", None),
        ]
        for raw in candidates:
            if not raw or not str(raw).startswith(("http://", "https://")):
                continue
            url = str(raw).rstrip("/")
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls


async def crawl_urls(
    urls: list[str],
    *,
    config: Any | None = None,
    timeout_sec: float = 15.0,
    max_concurrent: int = 3,
) -> list[CrawlResult]:
    """Crawl explicit public URLs with polite rate limiting."""
    if not urls:
        return []

    crawl_tool: Any | None = None
    try:
        from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool

        crawl_tool = WizsearchCrawlTool(config={})
    except ImportError:
        logger.debug("WizsearchCrawlTool not available", exc_info=True)
        return [CrawlResult(url=u, success=False, error="crawl_unavailable") for u in urls]

    polite_client = PoliteHTTPClient(
        max_retries=getattr(config, "polite_retry_max", 3) if config else 3,
        base_delay=getattr(config, "polite_retry_base_delay", 1.0) if config else 1.0,
    )

    import asyncio

    sem = asyncio.Semaphore(max(1, max_concurrent))
    results: list[CrawlResult] = []

    async def _crawl_one(url: str) -> CrawlResult:
        async with sem:
            try:

                async def _do_crawl(_method: str, _target: str, **_kw: Any) -> str:
                    return await asyncio.wait_for(crawl_tool._arun(url=url), timeout=timeout_sec)

                raw = await polite_client.request("GET", url, request_func=_do_crawl)
                if raw and isinstance(raw, str) and not raw.startswith("Error"):
                    return CrawlResult(url=url, content=raw[:8000], success=True)
                return CrawlResult(url=url, success=False, error="empty_response")
            except TimeoutError:
                return CrawlResult(url=url, success=False, error="timeout")
            except Exception as exc:
                logger.debug("Crawl failed for %s", url, exc_info=True)
                return CrawlResult(url=url, success=False, error=str(exc))

    crawled = await asyncio.gather(*[_crawl_one(u) for u in urls])
    results.extend(crawled)
    return results
