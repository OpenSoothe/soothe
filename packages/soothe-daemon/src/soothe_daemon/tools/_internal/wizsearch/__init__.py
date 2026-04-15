"""Wizsearch-powered web search and page crawling tools.

Re-exports all public names so ``from soothe_daemon.tools.wizsearch import X`` works.
"""

from soothe_daemon.tools._internal.wizsearch._helpers import (
    WIZSEARCH_AVAILABLE,
    _check_wizsearch_available,
    _extract_domain,
    _maybe_apply_tavily_key,
    _normalize_engines,
    _require_wizsearch,
    _run_coro,
    _save_raw_results,
    _to_serializable_sources,
)
from soothe_daemon.tools._internal.wizsearch.crawl import WizsearchCrawlPageTool
from soothe_daemon.tools._internal.wizsearch.search import WizsearchSearchTool

__all__ = [
    "WIZSEARCH_AVAILABLE",
    "WizsearchCrawlPageTool",
    "WizsearchSearchTool",
    "_check_wizsearch_available",
    "_extract_domain",
    "_maybe_apply_tavily_key",
    "_normalize_engines",
    "_require_wizsearch",
    "_run_coro",
    "_save_raw_results",
    "_to_serializable_sources",
]


def create_wizsearch_tools(config: dict | None = None) -> list:
    """Create wizsearch tool instances.

    Args:
        config: Optional configuration dict with keys:
            - default_engines: List of default search engines
            - max_results_per_engine: Max results per engine
            - timeout: Request timeout in seconds

    Returns:
        List containing wizsearch search and crawl tools.
    """
    config = config or {}
    return [
        WizsearchSearchTool(config=config),
        WizsearchCrawlPageTool(config=config),
    ]
