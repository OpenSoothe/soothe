"""Wizsearch helpers and search/crawl implementation functions.

Provides helper utilities for wizsearch tools and
implementation functions for direct use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import urlparse

from soothe.utils.text_preview import preview_first
from soothe.utils.url_validation import validate_url

logger = logging.getLogger(__name__)

T = TypeVar("T")

WIZSEARCH_AVAILABLE = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_wizsearch_available() -> bool:
    """Check if wizsearch is available (lazy import)."""
    global WIZSEARCH_AVAILABLE
    if WIZSEARCH_AVAILABLE is None:
        try:
            import wizsearch  # noqa: F401

            WIZSEARCH_AVAILABLE = True
        except ImportError:
            WIZSEARCH_AVAILABLE = False
    return WIZSEARCH_AVAILABLE


def _require_wizsearch() -> None:
    """Ensure optional wizsearch dependency is available."""
    if not _check_wizsearch_available():
        msg = "wizsearch package is not installed. Install it with `pip install soothe[wizsearch]`."
        raise ImportError(msg)


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


def _extract_domain(url: str) -> str:
    """Return the bare domain from a URL, e.g. 'bbc.com'."""
    try:
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return ""


def _save_raw_results(query: str, result: object) -> None:
    """Persist the full search result JSON to the current thread's run dir.

    Writes to ``$SOOTHE_HOME/data/threads/{thread_id}/search_results/{ts}_{slug}.json``.
    Fails silently if no run directory is active.
    """
    from soothe.utils.runtime import current_run_dir

    run_dir = current_run_dir.get()
    if run_dir is None:
        return

    try:
        search_dir = run_dir / "search_results"
        search_dir.mkdir(parents=True, exist_ok=True)

        slug = preview_first(re.sub(r"[^\w]+", "_", query), 60).strip("_")
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{slug}.json"

        payload = {
            "query": getattr(result, "query", query),
            "answer": getattr(result, "answer", None),
            "sources": _to_serializable_sources(result),
            "response_time": getattr(result, "response_time", None),
            "metadata": getattr(result, "metadata", None),
        }
        (search_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.debug("Raw search results saved: %s", filename)
    except Exception:
        logger.debug("Failed to save raw search results", exc_info=True)


def _run_coro(coro: Awaitable[T]) -> T:
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


# ---------------------------------------------------------------------------
# Search implementation
# ---------------------------------------------------------------------------

_SOURCE_CONTENT_MAX_LEN: int = 250


def _build_result_payload(result: object) -> str:
    """Build a tool output that guides synthesis without leaking raw data.

    Args:
        result: WizSearch result object.

    Returns:
        Formatted search result string.
    """
    query = getattr(result, "query", "")
    answer = getattr(result, "answer", None)
    sources = _to_serializable_sources(result)
    response_time = getattr(result, "response_time", None)

    time_str = f"{response_time:.1f}s" if response_time else "unknown"
    header = f'{len(sources)} results in {time_str} for "{query}"'

    if not sources:
        return f"{header}\nNo results found."

    lines: list[str] = []
    for i, src in enumerate(sources, 1):
        title = src.get("title", "Untitled")
        url = src.get("url", "")
        domain = _extract_domain(url) if url else ""
        content = src.get("content", "")
        if len(content) > _SOURCE_CONTENT_MAX_LEN:
            content = content[:_SOURCE_CONTENT_MAX_LEN] + "..."
        entry = f"{i}. {title}"
        if domain:
            entry += f" ({domain})"
        if content:
            entry += f"\n   {content}"
        lines.append(entry)

    body = "\n".join(lines)
    parts = [
        header,
        "",
        "<search_data>",
    ]
    if answer:
        parts.append(f"Direct answer: {answer}")
        parts.append("")
    parts.extend(
        [
            body,
            "</search_data>",
            "",
            "Synthesize the search data into a clear answer. "
            "Do NOT reproduce raw results, source listings, or URLs.",
        ]
    )
    return "\n".join(parts)


def _log_engine_diagnostics(engines: list[str]) -> None:
    """Log diagnostic information about search engine configurations.

    Args:
        engines: List of engine names to check.
    """
    if "tavily" in engines:
        tavily_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("WIZSEARCH_TAVILY_API_KEY")
        if not tavily_key:
            logger.warning("Tavily API key NOT FOUND - Tavily search will fail")

    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if https_proxy or http_proxy:
        logger.info("Proxy configured: HTTPS=%s, HTTP=%s", https_proxy, http_proxy)


def _validate_engine_config(engines: list[str]) -> list[dict[str, Any]]:
    """Validate configuration for requested engines and return warnings.

    Args:
        engines: List of engine names to validate.

    Returns:
        List of warning dictionaries with engine, issue, message, action.
    """
    warnings = []

    for engine in engines:
        if engine == "tavily":
            key = os.environ.get("TAVILY_API_KEY") or os.environ.get("WIZSEARCH_TAVILY_API_KEY")
            if not key:
                warnings.append(
                    {
                        "engine": engine,
                        "issue": "missing_api_key",
                        "message": "TAVILY_API_KEY not found in environment",
                        "action": "Set TAVILY_API_KEY or WIZSEARCH_TAVILY_API_KEY environment variable",
                    }
                )

    return warnings


async def perform_wizsearch_search(
    query: str,
    max_results_per_engine: int = 10,
    timeout_seconds: int = 30,
    engines: list[str] | None = None,
    debug_mode: bool = False,
) -> str:
    """Perform web search using wizsearch.

    Args:
        query: Search query string.
        max_results_per_engine: Max results per engine (default: 10).
        timeout_seconds: Timeout in seconds (default: 30).
        engines: List of engines (default: ["tavily", "duckduckgo"]).
        debug_mode: Enable debug output (default: False).

    Returns:
        Formatted search result string.
    """
    from soothe.utils.output_capture import capture_subagent_output

    _require_wizsearch()
    _maybe_apply_tavily_key()

    from wizsearch import WizSearch, WizSearchConfig

    # Default engines if not provided
    default_engines = engines or ["tavily", "duckduckgo"]

    config_kwargs: dict[str, object] = {
        "max_results_per_engine": max_results_per_engine,
        "timeout": timeout_seconds,
        "fail_silently": not debug_mode,
        "enabled_engines": default_engines,
    }

    if debug_mode:
        logger.info("Wizsearch debug mode enabled: fail_silently=False, output_suppression=False")

    _log_engine_diagnostics(default_engines)
    validation_warnings = _validate_engine_config(default_engines)
    for warning in validation_warnings:
        logger.warning(
            "Engine %s: %s - %s", warning["engine"], warning["issue"], warning["message"]
        )

    try:
        with capture_subagent_output("wizsearch", suppress=not debug_mode):
            searcher = WizSearch(config=WizSearchConfig(**config_kwargs))
            result = await searcher.search(query=query)

            if hasattr(result, "metadata") and result.metadata:
                engine_status = result.metadata.get("engine_status", {})
                for engine_name, status in engine_status.items():
                    logger.debug("Engine %s: %s", engine_name, status)

            _ = _to_serializable_sources(result)  # Keep for potential future use
            _save_raw_results(query, result)
            return _build_result_payload(result)
    except Exception as exc:
        logger.exception("Search failed with engines %s", default_engines)

        return f'Search failed for "{query}": {exc}'


# ---------------------------------------------------------------------------
# Crawl implementation
# ---------------------------------------------------------------------------


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
