"""Web search capability with wizsearch, Tavily, and DuckDuckGo fallbacks."""

from __future__ import annotations

import logging
import re
from typing import Any

from soothe.subagents.deep_research.json_util import compact_search_query
from soothe.subagents.deep_research.protocol import GatherContext, SourceResult
from soothe.toolkits.url_crawl.polite_http import (
    DomainRateLimiter,
    PoliteHTTPClient,
    RateLimit,
    RateLimitConfig,
)

logger = logging.getLogger(__name__)

_CAPABILITY_DESCRIPTION = (
    "Search the public web for documentation, news, tutorials, product pages, "
    "and current information."
)

_MIN_RAW_LENGTH_FOR_FALLBACK = 50


class WebSearchSource:
    """Multi-engine web search with optional-backend fallbacks."""

    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._wizsearch_tool: Any | None = None
        self._tavily_tool: Any | None = None
        self._ddg_tool: Any | None = None
        self._wizsearch_tried = False
        self._tavily_tried = False
        self._ddg_tried = False
        self._polite_client: PoliteHTTPClient | None = None
        self._init_polite_client()

    def _init_polite_client(self) -> None:
        """Initialize polite HTTP client from config."""
        if not self._config:
            return

        # Get DeepResearchConfig from subagents.deep_research if available
        dr_config = None
        if hasattr(self._config, "subagents"):
            subagent = self._config.subagents.get("deep_research")
            if subagent and hasattr(subagent, "config"):
                dr_config = subagent.config

        if not dr_config:
            return

        enable_polite = getattr(dr_config, "enable_polite_concurrency", True)
        if not enable_polite:
            logger.debug("Polite concurrency disabled for WebSearchSource")
            return

        # Build rate limit config with domain overrides
        domain_limits: dict[str, RateLimit] = {
            "wizsearch": RateLimit(rps=2.0, burst=5, concurrent=8),
            "tavily": RateLimit(rps=1.0, burst=3, concurrent=5),
            "duckduckgo": RateLimit(rps=2.0, burst=5, concurrent=10),
        }

        # Apply domain overrides from config
        domain_overrides = getattr(dr_config, "polite_domain_overrides", {})
        for domain, overrides in domain_overrides.items():
            if domain in domain_limits:
                domain_limits[domain] = RateLimit(
                    rps=overrides.get("rps", domain_limits[domain].rps),
                    burst=overrides.get("burst", domain_limits[domain].burst),
                    concurrent=overrides.get("concurrent", domain_limits[domain].concurrent),
                )

        rate_limit_config = RateLimitConfig(limits=domain_limits)
        rate_limiter = DomainRateLimiter(config=rate_limit_config)

        self._polite_client = PoliteHTTPClient(
            rate_limiter=rate_limiter,
            max_retries=getattr(dr_config, "polite_retry_max", 3),
            base_delay=getattr(dr_config, "polite_retry_base_delay", 1.0),
            enable_circuit_breaker=True,
            circuit_breaker_threshold=getattr(dr_config, "polite_circuit_breaker_threshold", 5),
            circuit_breaker_reset_sec=getattr(dr_config, "polite_circuit_breaker_reset_sec", 60.0),
        )
        logger.debug("Polite HTTP client initialized for WebSearchSource")

    def _wizsearch_config(self) -> dict[str, Any]:
        web_search_config: dict[str, Any] = {}
        if self._config and hasattr(self._config, "tools"):
            ws = getattr(self._config.tools, "wizsearch", None)
            if ws:
                web_search_config = {
                    "default_engines": ws.default_engines,
                    "max_results_per_engine": ws.max_results_per_engine,
                    "timeout": ws.timeout,
                }
        return web_search_config

    def _ensure_wizsearch(self) -> None:
        if self._wizsearch_tried:
            return
        self._wizsearch_tried = True
        try:
            from soothe.toolkits.wizsearch import WizsearchSearchTool

            self._wizsearch_tool = WizsearchSearchTool(config=self._wizsearch_config())
        except ImportError:
            logger.debug("WizsearchSearchTool not available", exc_info=True)

    def _ensure_tavily(self) -> None:
        if self._tavily_tried:
            return
        self._tavily_tried = True
        try:
            from langchain_tavily import TavilySearch

            self._tavily_tool = TavilySearch(max_results=8)
        except ImportError:
            try:
                from langchain_community.tools.tavily_search import TavilySearchResults

                self._tavily_tool = TavilySearchResults(max_results=8)
            except ImportError:
                logger.debug("Tavily search not available", exc_info=True)

    def _ensure_ddg(self) -> None:
        if self._ddg_tried:
            return
        self._ddg_tried = True
        try:
            from langchain_community.tools import DuckDuckGoSearchRun

            self._ddg_tool = DuckDuckGoSearchRun()
        except ImportError:
            logger.debug("DuckDuckGo search not available", exc_info=True)

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def source_type(self) -> str:
        return "web"

    async def _run_backend(self, tool: Any, query: str, domain: str = "default") -> str | None:
        """Run backend tool with optional polite client wrapping."""
        # Determine the domain for rate limiting based on tool type
        if self._polite_client and domain != "default":
            try:
                return await self._polite_client.request(
                    "GET",
                    f"https://{domain}.internal/search",
                    domain=domain,
                    request_func=self._execute_backend_tool,
                    tool=tool,
                    query=query,
                )
            except Exception as e:
                logger.debug("Polite backend request failed for %s: %s", domain, e)
                # Fall back to direct execution
                return await self._execute_backend_tool("GET", "", tool=tool, query=query)
        return await self._execute_backend_tool("GET", "", tool=tool, query=query)

    async def _execute_backend_tool(
        self, _method: str, _url: str, *, tool: Any, query: str
    ) -> str | None:
        """Execute the actual backend tool call."""
        if hasattr(tool, "_arun"):
            return await tool._arun(query)
        if hasattr(tool, "ainvoke"):
            out = await tool.ainvoke(query)
            return str(out) if out is not None else None
        if hasattr(tool, "_run"):
            return tool._run(query)
        if hasattr(tool, "invoke"):
            out = tool.invoke(query)
            return str(out) if out is not None else None
        return None

    async def _query_wizsearch_structured(self, search_q: str) -> list[SourceResult]:
        """Use wizsearch API directly so URLs are preserved for references."""
        try:
            from soothe.toolkits._internal.wizsearch import _check_wizsearch_available
        except ImportError:
            return []

        if not _check_wizsearch_available():
            return []

        ws_cfg = self._wizsearch_config()

        # Wrap wizsearch call with polite client if available
        if self._polite_client:
            try:
                result = await self._polite_client.request(
                    "GET",
                    "https://wizsearch.internal/search",
                    domain="wizsearch",
                    request_func=self._perform_wizsearch_search,
                    search_q=search_q,
                    ws_cfg=ws_cfg,
                )
            except Exception as e:
                logger.warning("Polite wizsearch request failed: %s", e)
                # Fall back to direct call
                result = await self._perform_wizsearch_search(
                    "GET", "", search_q=search_q, ws_cfg=ws_cfg
                )
        else:
            result = await self._perform_wizsearch_search(
                "GET", "", search_q=search_q, ws_cfg=ws_cfg
            )

        sources = getattr(result, "sources", []) or []
        if not sources:
            return []

        parsed: list[SourceResult] = []
        for src in sources:
            title = getattr(src, "title", "") or "Untitled"
            url = getattr(src, "url", "") or ""
            content = getattr(src, "content", "") or ""
            domain = ""
            if url:
                from soothe.toolkits._internal.wizsearch import _extract_domain

                domain = _extract_domain(url)
            if not content and not url:
                continue
            parsed.append(
                SourceResult(
                    content=(content or title)[:4000],
                    source_ref=url or domain or search_q,
                    source_name="web_search",
                    metadata={
                        "title": title,
                        "url": url or None,
                        "domain": domain or None,
                        "backend": "wizsearch",
                        "query": search_q,
                    },
                )
            )
        return parsed

    async def _perform_wizsearch_search(
        self, _method: str, _url: str, *, search_q: str, ws_cfg: dict[str, Any]
    ) -> Any:
        """Wrapper to call perform_wizsearch_search with proper signature."""
        from soothe.toolkits._internal.wizsearch import perform_wizsearch_search

        return await perform_wizsearch_search(
            query=search_q,
            max_results_per_engine=ws_cfg.get("max_results_per_engine", 10),
            timeout_seconds=ws_cfg.get("timeout", 30),
            engines=ws_cfg.get("default_engines") or ["tavily"],
        )

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        search_q = compact_search_query(query)

        structured = await self._query_wizsearch_structured(search_q)
        if structured:
            return structured

        self._ensure_wizsearch()
        if self._wizsearch_tool:
            try:
                raw = await self._run_backend(self._wizsearch_tool, search_q, domain="wizsearch")
                if raw:
                    parsed = self._parse_search_output(raw, search_q)
                    if parsed:
                        return parsed
            except Exception:
                logger.debug("Wizsearch failed for: %s", search_q, exc_info=True)

        self._ensure_tavily()
        if self._tavily_tool:
            try:
                raw = await self._run_backend(self._tavily_tool, search_q, domain="tavily")
                if raw:
                    return self._parse_plain_output(raw, "tavily", search_q)
            except Exception:
                logger.debug("Tavily failed for: %s", search_q, exc_info=True)

        self._ensure_ddg()
        if self._ddg_tool:
            try:
                raw = await self._run_backend(self._ddg_tool, search_q, domain="duckduckgo")
                if raw:
                    return self._parse_plain_output(raw, "duckduckgo", search_q)
            except Exception:
                logger.debug("DuckDuckGo failed for: %s", search_q, exc_info=True)

        logger.warning(
            "No web search backend available for query (install/upgrade soothe or set TAVILY_API_KEY)"
        )
        return []

    @staticmethod
    def _parse_plain_output(raw: str, backend: str, query: str) -> list[SourceResult]:
        if not raw or len(raw) < 10:
            return []
        return [
            SourceResult(
                content=raw[:4000],
                source_ref=backend,
                source_name="web_search",
                metadata={"backend": backend, "query": query},
            )
        ]

    @staticmethod
    def _parse_search_output(raw: str, query: str) -> list[SourceResult]:
        results: list[SourceResult] = []
        if (
            not raw
            or "No results found" in raw
            or "Search failed" in raw
            or "No search engines available" in raw
        ):
            return results

        pattern = re.compile(r"^(\d+)\.\s+(.+?)(?:\s+\(([^)]+)\))?$", re.MULTILINE)
        for match in pattern.finditer(raw):
            title = match.group(2).strip()
            domain = match.group(3) or ""
            source_ref = domain or query
            idx = match.end()
            content_lines: list[str] = []
            for line in raw[idx:].split("\n"):
                stripped = line.strip()
                if not stripped or re.match(r"^\d+\.", stripped):
                    break
                content_lines.append(stripped)
            content = " ".join(content_lines)
            if content:
                results.append(
                    SourceResult(
                        content=content,
                        source_ref=source_ref,
                        source_name="web_search",
                        metadata={"title": title, "domain": domain},
                    )
                )

        if not results and len(raw) > _MIN_RAW_LENGTH_FOR_FALLBACK:
            results.append(
                SourceResult(
                    content=raw[:2000],
                    source_ref=query,
                    source_name="web_search",
                )
            )
        return results
