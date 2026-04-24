"""Plain search implementation functions for wizsearch toolkit.

These functions implement the search logic without BaseTool wrapper,
allowing toolkit-level tools to call them directly.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from soothe.toolkits._internal.wizsearch._helpers import (
    _extract_domain,
    _maybe_apply_tavily_key,
    _require_wizsearch,
    _save_raw_results,
    _to_serializable_sources,
)

logger = logging.getLogger(__name__)

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
