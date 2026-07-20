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
import time
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import urlparse

from soothe_nano.utils.text_preview import log_preview, preview_first
from soothe_nano.utils.url_validation import validate_url

logger = logging.getLogger("soothe_nano.toolkits._internal.wizsearch")

_LOG_QUERY_CHARS = 120
_LOG_URL_CHARS = 160

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
        msg = "wizsearch package is not installed. Install/upgrade soothe (includes research dependencies): `pip install -U soothe`."
        raise ImportError(msg)


def _wizsearch_library_version() -> str:
    """Return installed wizsearch package version when importable."""
    try:
        import importlib.metadata as importlib_metadata

        return importlib_metadata.version("wizsearch")
    except Exception:
        return "unknown"


def _log_wizsearch_search_start(
    *,
    query: str,
    engines: list[str],
    max_results_per_engine: int,
    timeout_seconds: int,
    debug_mode: bool,
) -> None:
    """Log search invocation parameters before calling the wizsearch library."""
    logger.info(
        "[Wizsearch] search start query=%r engines=%s max_results=%d timeout=%ds "
        "debug=%s library=%s",
        log_preview(query, chars=_LOG_QUERY_CHARS),
        engines,
        max_results_per_engine,
        timeout_seconds,
        debug_mode,
        _wizsearch_library_version(),
    )


def _log_wizsearch_search_done(
    *,
    query: str,
    engines: list[str],
    elapsed_ms: int,
    source_count: int,
    response_time: float | None,
    engine_status: dict[str, Any] | None,
) -> None:
    """Log search completion metrics after wizsearch returns."""
    time_str = f"{response_time:.1f}s" if response_time is not None else "unknown"
    logger.info(
        "[Wizsearch] search done query=%r engines=%s elapsed_ms=%d sources=%d "
        "library_response_time=%s",
        log_preview(query, chars=_LOG_QUERY_CHARS),
        engines,
        elapsed_ms,
        source_count,
        time_str,
    )
    if engine_status:
        for engine_name, status in engine_status.items():
            logger.info("[Wizsearch] engine %s: %s", engine_name, status)


def _log_wizsearch_crawl_start(
    *,
    url: str,
    content_format: str,
    only_text: bool,
) -> None:
    """Log crawl invocation parameters before calling PageCrawler."""
    logger.info(
        "[Wizsearch] crawl start url=%r format=%s only_text=%s library=%s",
        log_preview(url, chars=_LOG_URL_CHARS),
        content_format,
        only_text,
        _wizsearch_library_version(),
    )


def _log_wizsearch_crawl_done(
    *,
    url: str,
    elapsed_ms: int,
    content_length: int,
    error: str | None = None,
) -> None:
    """Log crawl completion metrics."""
    if error:
        logger.warning(
            "[Wizsearch] crawl done url=%r elapsed_ms=%d status=error message=%s",
            log_preview(url, chars=_LOG_URL_CHARS),
            elapsed_ms,
            log_preview(error, chars=200),
        )
        return
    logger.info(
        "[Wizsearch] crawl done url=%r elapsed_ms=%d content_chars=%d",
        log_preview(url, chars=_LOG_URL_CHARS),
        elapsed_ms,
        content_length,
    )


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
    In virtual mode (IG-405), writes to ``/.soothe/data/threads/{thread_id}/search_results/``.
    Fails silently if no run directory is active.
    """
    from soothe_nano.utils.runtime import current_run_dir
    from soothe_nano.workspace import (
        FrameworkFilesystem,
        get_virtual_home,
        get_virtual_mode,
    )

    run_dir = current_run_dir.get()
    if run_dir is None:
        return

    try:
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
        content = json.dumps(payload, ensure_ascii=False, indent=2)

        # IG-405: Use backend when virtual mode
        if get_virtual_mode():
            backend = FrameworkFilesystem.get()
            if backend is not None:
                # Compute virtual path for search results
                virtual_home = get_virtual_home()
                search_rel = run_dir.relative_to(virtual_home) / "search_results"
                virtual_dir = f"/.soothe/{search_rel.as_posix()}"
                virtual_file = f"{virtual_dir}/{filename}"

                try:
                    backend.mkdir(virtual_dir, recursive=True)
                    backend.write(virtual_file, content)
                    logger.debug("Raw search results saved (virtual): %s", filename)
                    return
                except Exception:
                    logger.debug("Backend write failed, falling back to direct", exc_info=True)

        # Non-virtual mode or fallback: direct Path operations
        search_dir = run_dir / "search_results"
        search_dir.mkdir(parents=True, exist_ok=True)
        (search_dir / filename).write_text(content, encoding="utf-8")
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
        logger.error("[Wizsearch] sync tool invoked inside running event loop")
        raise RuntimeError(msg)
    return loop.run_until_complete(coro)


def _maybe_apply_tavily_key() -> None:
    """Backfill TAVILY_API_KEY from alternate env name when present."""
    if os.environ.get("TAVILY_API_KEY"):
        return
    alt = os.environ.get("WIZSEARCH_TAVILY_API_KEY")
    if alt:
        os.environ["TAVILY_API_KEY"] = alt


_PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")


def normalize_proxy_url(proxy: str | None) -> str | None:
    """Normalize a host:port or URL into an ``http://`` proxy URL."""
    if proxy is None:
        return None
    text = str(proxy).strip()
    if not text:
        return None
    if "://" not in text:
        text = f"http://{text}"
    return text


@contextmanager
def wizsearch_proxy_env(proxy: str | None) -> Iterator[str | None]:
    """Temporarily set HTTP(S)_PROXY for wizsearch when config proxy is set.

    Existing process proxy env vars take precedence (left unchanged). Yields the
    effective proxy URL actually used (env or config), or ``None``.
    """
    normalized = normalize_proxy_url(proxy)
    for env_key in _PROXY_ENV_KEYS:
        existing = os.environ.get(env_key, "").strip()
        if existing:
            yield existing
            return
    if not normalized:
        yield None
        return
    saved = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    try:
        for key in _PROXY_ENV_KEYS:
            os.environ[key] = normalized
        logger.debug("[Wizsearch] using config proxy %s", normalized)
        yield normalized
    finally:
        for key, prior in saved.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


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
        "<SEARCH_DATA>",
    ]
    if answer:
        parts.append(f"Direct answer: {answer}")
        parts.append("")
    parts.extend(
        [
            body,
            "</SEARCH_DATA>",
            "",
            "Synthesize the search data into a clear answer. "
            "Do NOT reproduce raw results, source listings, or URLs.",
        ]
    )
    return "\n".join(parts)


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

    if not warnings:
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        if https_proxy or http_proxy:
            logger.info("Proxy configured: HTTPS=%s, HTTP=%s", https_proxy, http_proxy)

    return warnings


async def perform_wizsearch_search(
    query: str,
    max_results_per_engine: int = 10,
    timeout_seconds: int = 30,
    engines: list[str] | None = None,
    debug_mode: bool = False,
    proxy: str | None = None,
) -> str:
    """Perform web search using wizsearch.

    Args:
        query: Search query string.
        max_results_per_engine: Max results per engine (default: 10).
        timeout_seconds: Timeout in seconds (default: 30).
        engines: List of engines (default: ["tavily", "duckduckgo"]).
        debug_mode: Enable debug output (default: False).
        proxy: Optional HTTP(S) proxy URL (e.g. ``http://127.0.0.1:7890``).

    Returns:
        Formatted search result string.
    """
    from soothe_nano.utils.output_capture import capture_subagent_output

    _require_wizsearch()
    _maybe_apply_tavily_key()

    from wizsearch import WizSearch, WizSearchConfig

    # Default engines if not provided
    default_engines = engines or ["tavily"]

    config_kwargs: dict[str, object] = {
        "max_results_per_engine": max_results_per_engine,
        "timeout": timeout_seconds,
        "fail_silently": not debug_mode,
        "enabled_engines": default_engines,
    }

    if debug_mode:
        logger.info("Wizsearch debug mode enabled: fail_silently=False, output_suppression=False")

    validation_warnings = _validate_engine_config(default_engines)
    for warning in validation_warnings:
        logger.warning(
            "Engine %s: %s - %s", warning["engine"], warning["issue"], warning["message"]
        )

    # Short-circuit when every requested engine is misconfigured
    all_misconfigured = len(validation_warnings) > 0 and len(validation_warnings) == len(
        default_engines
    )
    if all_misconfigured:
        issues = "; ".join(f"{w['engine']}: {w['issue']}" for w in validation_warnings)
        logger.warning(
            "[Wizsearch] search skipped query=%r engines=%s reason=all_misconfigured (%s)",
            log_preview(query, chars=_LOG_QUERY_CHARS),
            default_engines,
            issues,
        )
        return f'No search engines available for "{query}" ({issues})'

    _log_wizsearch_search_start(
        query=query,
        engines=default_engines,
        max_results_per_engine=max_results_per_engine,
        timeout_seconds=timeout_seconds,
        debug_mode=debug_mode,
    )
    started = time.perf_counter()
    try:
        with (
            wizsearch_proxy_env(proxy),
            capture_subagent_output("wizsearch", suppress=not debug_mode),
        ):
            searcher = WizSearch(config=WizSearchConfig(**config_kwargs))
            result = await searcher.search(query=query)

            sources = _to_serializable_sources(result)
            engine_status: dict[str, Any] | None = None
            if hasattr(result, "metadata") and result.metadata:
                raw_status = result.metadata.get("engine_status", {})
                if isinstance(raw_status, dict):
                    engine_status = raw_status

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response_time = getattr(result, "response_time", None)
            _log_wizsearch_search_done(
                query=query,
                engines=default_engines,
                elapsed_ms=elapsed_ms,
                source_count=len(sources),
                response_time=float(response_time) if response_time is not None else None,
                engine_status=engine_status,
            )

            _save_raw_results(query, result)
            return _build_result_payload(result)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "[Wizsearch] search failed query=%r engines=%s elapsed_ms=%d error=%s",
            log_preview(query, chars=_LOG_QUERY_CHARS),
            default_engines,
            elapsed_ms,
            exc,
        )

        return f'Search failed for "{query}": {exc}'


# ---------------------------------------------------------------------------
# Crawl implementation
# ---------------------------------------------------------------------------


async def perform_wizsearch_crawl(
    url: str,
    content_format: str = "markdown",
    *,
    only_text: bool = False,
    proxy: str | None = None,
) -> dict[str, object]:
    """Crawl a web page using wizsearch PageCrawler.

    Args:
        url: URL to crawl.
        content_format: Output format ('markdown', 'html', 'text').
        only_text: Extract only text content (default: False).
        proxy: Optional HTTP(S) proxy URL (e.g. ``http://127.0.0.1:7890``).

    Returns:
        Dict with url, content_format, only_text, headless, content, content_length, error.
    """
    from soothe_nano.utils.output_capture import capture_subagent_output

    _require_wizsearch()

    from wizsearch import PageCrawler

    selected_format = content_format.strip().lower()
    if selected_format not in {"markdown", "html", "text"}:
        selected_format = "markdown"

    _log_wizsearch_crawl_start(
        url=url,
        content_format=selected_format,
        only_text=only_text,
    )
    started = time.perf_counter()

    validated_url, error = validate_url(url)
    if error:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log_wizsearch_crawl_done(url=url, elapsed_ms=elapsed_ms, content_length=0, error=error)
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
        with (
            wizsearch_proxy_env(proxy) as effective_proxy,
            capture_subagent_output("wizsearch", suppress=True),
        ):
            crawler = PageCrawler(
                url=validated_url,
                content_format=selected_format,
                only_text=only_text,
                proxy=effective_proxy,
            )
            content = await crawler.crawl()

        content_text = content or ""
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log_wizsearch_crawl_done(
            url=validated_url,
            elapsed_ms=elapsed_ms,
            content_length=len(content_text),
        )
        return {
            "url": validated_url,
            "content_format": selected_format,
            "only_text": only_text,
            "headless": True,
            "content": content_text,
            "content_length": len(content_text),
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        error_str = str(exc).lower()
        if "timeout" in error_str:
            logger.warning(
                "[Wizsearch] crawl timed out url=%r elapsed_ms=%d",
                log_preview(validated_url, chars=_LOG_URL_CHARS),
                elapsed_ms,
            )
        elif "connection" in error_str:
            logger.warning(
                "[Wizsearch] crawl connection failed url=%r elapsed_ms=%d",
                log_preview(validated_url, chars=_LOG_URL_CHARS),
                elapsed_ms,
            )
        elif "javascript" in error_str or "render" in error_str:
            logger.warning(
                "[Wizsearch] crawl render issue url=%r elapsed_ms=%d",
                log_preview(validated_url, chars=_LOG_URL_CHARS),
                elapsed_ms,
            )
        else:
            logger.exception(
                "[Wizsearch] crawl failed url=%r elapsed_ms=%d",
                log_preview(validated_url, chars=_LOG_URL_CHARS),
                elapsed_ms,
            )

        _log_wizsearch_crawl_done(
            url=validated_url,
            elapsed_ms=elapsed_ms,
            content_length=0,
            error=str(exc),
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
