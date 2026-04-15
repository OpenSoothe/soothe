"""Shared helpers for wizsearch tools."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable
from typing import TypeVar

from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

T = TypeVar("T")

WIZSEARCH_AVAILABLE = None


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


def _normalize_engines(engines: list[str] | str | None) -> list[str] | None:
    """Normalize engine list input from list, JSON string, or comma-separated string.

    LLMs sometimes pass a stringified JSON array (e.g. ``'["google", "bing"]'``)
    instead of an actual list.  We try ``json.loads`` first so the individual
    engine names are preserved correctly.
    """
    if engines is None:
        return None
    if isinstance(engines, list):
        normalized = [str(engine).strip() for engine in engines if str(engine).strip()]
        return normalized or None
    if isinstance(engines, str):
        import json

        try:
            parsed = json.loads(engines)
            if isinstance(parsed, list):
                normalized = [str(e).strip() for e in parsed if str(e).strip()]
                return normalized or None
        except (json.JSONDecodeError, ValueError):
            pass
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


def _extract_domain(url: str) -> str:
    """Return the bare domain from a URL, e.g. 'bbc.com'."""
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return ""


def _save_raw_results(query: str, result: object) -> None:
    """Persist the full search result JSON to the current thread's run dir.

    Writes to ``$SOOTHE_HOME/runs/{thread_id}/search_results/{ts}_{slug}.json``.
    Fails silently if no run directory is active.
    """
    import json
    import re
    from datetime import UTC, datetime

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
