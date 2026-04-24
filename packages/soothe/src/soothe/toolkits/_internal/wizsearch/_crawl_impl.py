"""Plain crawl implementation functions for wizsearch toolkit.

These functions implement the crawl logic without BaseTool wrapper,
allowing toolkit-level tools to call them directly.
"""

from __future__ import annotations

import logging

from soothe.toolkits._internal.wizsearch._helpers import _require_wizsearch
from soothe.utils.url_validation import validate_url

logger = logging.getLogger(__name__)


async def perform_wizsearch_crawl(
    url: str,
    content_format: str = "markdown",
    *,
    only_text: bool = False,
) -> dict[str, object]:
    """Crawl a web page using wizsearch PageCrawler.

    Args:
        url: URL to crawl.
        content_format: Output format ('markdown', 'html', 'text').
        only_text: Extract only text content (default: False).

    Returns:
        Dict with url, content_format, only_text, headless, content, content_length, error.
    """
    from soothe.utils.output_capture import capture_subagent_output

    _require_wizsearch()

    from wizsearch import PageCrawler

    selected_format = content_format.strip().lower()
    if selected_format not in {"markdown", "html", "text"}:
        selected_format = "markdown"

    validated_url, error = validate_url(url)
    if error:
        logger.warning("Invalid URL: %s", error)
        return {
            "url": url,
            "content_format": selected_format,
            "only_text": only_text,
            "headless": True,
            "content": "",
            "content_length": 0,
            "error": error,
        }

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
    except Exception as exc:
        logger.exception("Crawl failed for %s", validated_url)

        error_str = str(exc).lower()
        if "timeout" in error_str:
            logger.warning("Crawl timed out - consider increasing timeout or checking network")
        elif "connection" in error_str:
            logger.warning("Connection failed - check URL accessibility and proxy settings")
        elif "javascript" in error_str or "render" in error_str:
            logger.warning("JavaScript rendering issue - page may require JS execution")

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
