"""Multi-engine web search tool powered by wizsearch."""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.core.events import (
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
    TOOL_WEBSEARCH_SEARCH_STARTED,
)
from soothe.tools._internal.wizsearch._helpers import (
    _extract_domain,
    _maybe_apply_tavily_key,
    _require_wizsearch,
    _run_coro,
    _save_raw_results,
    _to_serializable_sources,
)

logger = logging.getLogger(__name__)


class WizsearchSearchTool(BaseTool):
    """Multi-engine web search tool powered by wizsearch."""

    name: str = "wizsearch_search"
    description: str = (
        "Search the web using multiple engines. "
        "For time-sensitive queries (e.g., 'latest news', 'recent events'), "
        "first use the current_datetime tool to know today's date, then include appropriate "
        "time qualifiers (year, month) in your search query to get the most recent results. "
        "Inputs: `query` (required), `max_results_per_engine` (default: 10), "
        "`timeout` seconds (default: 30). "
        "Returns a text summary of search results with titles, URLs, and content snippets. "
        "Use these results to compose your answer; do NOT echo the raw results to the user."
    )
    default_max_results_per_engine: int = Field(default=10)
    default_timeout: int = Field(default=30)
    default_engines: list[str] = Field(default_factory=lambda: ["tavily", "duckduckgo"])
    config: dict[str, Any] = Field(default_factory=dict)
    _debug_mode: bool = False

    def __init__(self, **data: Any) -> None:
        """Initialize wizsearch search tool with optional config override.

        Args:
            **data: Tool configuration, including 'config' dict with
                'default_engines', 'max_results_per_engine', 'timeout', etc.
        """
        super().__init__(**data)
        if self.config:
            if "default_engines" in self.config:
                self.default_engines = self.config["default_engines"]
            if "max_results_per_engine" in self.config:
                self.default_max_results_per_engine = self.config["max_results_per_engine"]
            if "timeout" in self.config:
                self.default_timeout = self.config["timeout"]
            self._debug_mode = self.config.get("debug", False)

    def _log_engine_diagnostics(self, engines: list[str]) -> None:
        """Log diagnostic information about search engine configurations."""
        if "tavily" in engines:
            tavily_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("WIZSEARCH_TAVILY_API_KEY")
            if not tavily_key:
                logger.warning("Tavily API key NOT FOUND - Tavily search will fail")

        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        if https_proxy or http_proxy:
            logger.info("Proxy configured: HTTPS=%s, HTTP=%s", https_proxy, http_proxy)

    def _validate_engine_config(self, engines: list[str]) -> list[dict[str, Any]]:
        """Validate configuration for requested engines and return warnings."""
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

    _SOURCE_CONTENT_MAX_LEN: int = 250

    def _build_result_payload(self, result: object) -> str:
        """Build a tool output that guides synthesis without leaking raw data."""
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
            if len(content) > self._SOURCE_CONTENT_MAX_LEN:
                content = content[: self._SOURCE_CONTENT_MAX_LEN] + "…"
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

    async def _perform_search(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        from wizsearch import WizSearch, WizSearchConfig

        from soothe.utils.output_capture import capture_subagent_output
        from soothe.utils.progress import emit_progress

        _require_wizsearch()
        _maybe_apply_tavily_key()

        config_kwargs: dict[str, object] = {
            "max_results_per_engine": max_results_per_engine or self.default_max_results_per_engine,
            "timeout": timeout_seconds or self.default_timeout,
            "fail_silently": not self._debug_mode,
            "enabled_engines": self.default_engines,
        }

        if self._debug_mode:
            logger.info("Wizsearch debug mode enabled: fail_silently=False, output_suppression=False")

        self._log_engine_diagnostics(self.default_engines)
        validation_warnings = self._validate_engine_config(self.default_engines)
        for warning in validation_warnings:
            logger.warning("Engine %s: %s - %s", warning["engine"], warning["issue"], warning["message"])

        emit_progress(
            {
                "type": TOOL_WEBSEARCH_SEARCH_STARTED,
                "query": query,
                "engines": self.default_engines,
                "tool": "wizsearch_search",
                "tool_group": "websearch",
            },
            logger,
        )

        try:
            with capture_subagent_output("wizsearch", suppress=not self._debug_mode):
                searcher = WizSearch(config=WizSearchConfig(**config_kwargs))
                result = await searcher.search(query=query)

                if hasattr(result, "metadata") and result.metadata:
                    engine_status = result.metadata.get("engine_status", {})
                    for engine_name, status in engine_status.items():
                        logger.debug("Engine %s: %s", engine_name, status)

                sources = _to_serializable_sources(result)
                emit_progress(
                    {
                        "type": TOOL_WEBSEARCH_SEARCH_COMPLETED,
                        "query": query,
                        "result_count": len(sources),
                        "response_time": getattr(result, "response_time", None),
                        "tool": "wizsearch_search",
                        "tool_group": "websearch",
                    },
                    logger,
                )
                _save_raw_results(query, result)
                return self._build_result_payload(result)
        except Exception as exc:
            logger.exception("Search failed with engines %s", self.default_engines)

            emit_progress(
                {
                    "type": TOOL_WEBSEARCH_SEARCH_FAILED,
                    "query": query,
                    "error": str(exc),
                    "engines": self.default_engines,
                    "engine_status": getattr(exc, "engine_status", {}),
                    "debug_mode": self._debug_mode,
                    "tool": "wizsearch_search",
                    "tool_group": "websearch",
                },
                logger,
            )
            return f'Search failed for "{query}": {exc}'

    def _run(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        return _run_coro(
            self._perform_search(
                query=query,
                max_results_per_engine=max_results_per_engine,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _arun(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        return await self._perform_search(
            query=query,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )
