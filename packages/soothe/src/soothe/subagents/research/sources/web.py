"""Web search InformationSource using wizsearch backend."""

from __future__ import annotations

import logging
from typing import Any

from soothe.subagents.research.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_KEYWORD_MATCH_THRESHOLD = 0.3
_LOW_RELEVANCE_SCORE = 0.15
_CODE_PENALTY_SCORE = 0.25
_ACADEMIC_HINT_SCORE = 0.5
_DEFAULT_WEB_SCORE = 0.6
_MIN_RAW_LENGTH_FOR_FALLBACK = 50
_MIN_PLAIN_OUTPUT_LENGTH = 10


class WebSource:
    """Information source backed by multi-engine web search.

    Uses ``WizsearchSearchTool`` as the backend with engines configured via
    wizsearch.default_engines in config.yml. Results are normalised into
    ``SourceResult`` instances.

    Args:
        config: Optional Soothe config for web search backend settings.
    """

    def __init__(
        self,
        config: Any | None = None,
    ) -> None:
        """Initialize the web source with optional config."""
        self._config = config
        self._search_tool: Any | None = None
        self._wikipedia_tool: Any | None = None
        self._tools_loaded = False

    def _ensure_wikipedia(self) -> None:
        """Lazy-load Wikipedia tool for encyclopedic queries."""
        if self._wikipedia_tool is not None:
            return
        try:
            from langchain_community.tools import WikipediaQueryRun
            from langchain_community.utilities import WikipediaAPIWrapper

            self._wikipedia_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        except Exception:
            logger.debug("Wikipedia tool not available", exc_info=True)

    def _ensure_tools(self) -> None:
        if self._search_tool is not None:
            return
        try:
            from soothe.toolkits.wizsearch import WizsearchSearchTool

            web_search_config: dict[str, Any] = {}
            if self._config and hasattr(self._config, "tools"):
                ws = getattr(self._config.tools, "wizsearch", None)
                if ws:
                    web_search_config = {
                        "default_engines": ws.default_engines,
                        "max_results_per_engine": ws.max_results_per_engine,
                        "timeout": ws.timeout,
                    }

            self._search_tool = WizsearchSearchTool(config=web_search_config)
        except ImportError:
            logger.debug("WizsearchSearchTool not available - wizsearch package not installed")
            self._search_tool = None

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "web_search"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "web"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Execute web search and return normalised results.

        Also queries Wikipedia for encyclopedic queries.

        Args:
            query: Search query string.
            context: Current research context.

        Returns:
            List of SourceResult from web search engines and Wikipedia.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        # Web search
        if self._search_tool:
            try:
                raw = await self._search_tool._arun(query=query)
                results.extend(self._parse_search_output(raw, query))
            except Exception:
                logger.debug("Web search failed for: %s", query, exc_info=True)

        # Wikipedia for encyclopedic queries
        if self._is_encyclopedic_query(query.lower()):
            self._ensure_wikipedia()
            if self._wikipedia_tool:
                try:
                    raw = await self._wikipedia_tool._arun(query)
                    if raw and "No good" not in raw:
                        results.append(
                            SourceResult(
                                content=raw[:3000],
                                source_ref="wikipedia",
                                source_name="web_search",
                                metadata={"sub_source": "wikipedia"},
                            )
                        )
                except Exception:
                    logger.debug("Wikipedia query failed for: %s", query, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Web search is the default fallback -- always somewhat relevant."""
        from ._scoring import (
            _ACADEMIC_KEYWORDS,
            _CODE_KEYWORDS,
            has_file_path,
            keyword_score,
        )
        from .filesystem import FilesystemSource

        if has_file_path(query) or FilesystemSource._looks_like_path(
            query.strip().split()[0] if query.strip() else ""
        ):
            return _LOW_RELEVANCE_SCORE

        code_score = keyword_score(query, _CODE_KEYWORDS)
        if code_score > _KEYWORD_MATCH_THRESHOLD:
            return _CODE_PENALTY_SCORE

        academic_score = keyword_score(query, _ACADEMIC_KEYWORDS)
        if academic_score > _KEYWORD_MATCH_THRESHOLD:
            return _ACADEMIC_HINT_SCORE

        return _DEFAULT_WEB_SCORE

    # -- Heuristics ----------------------------------------------------------

    @staticmethod
    def _is_encyclopedic_query(q: str) -> bool:
        """Check if query looks encyclopedic (definitions, concepts, etc.)."""
        from ._scoring import _ENCYCLOPEDIC_KEYWORDS, keyword_score

        return keyword_score(q, _ENCYCLOPEDIC_KEYWORDS, weight=0.2) > 0.15

    # -- Parsing helpers -----------------------------------------------------

    @staticmethod
    def _parse_search_output(raw: str, query: str) -> list[SourceResult]:
        """Parse structured search output (from wizsearch backend) into SourceResults."""
        results: list[SourceResult] = []
        if not raw or "No results found" in raw or "Search failed" in raw:
            return results

        import re

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

    @staticmethod
    def _parse_plain_output(raw: str, source_label: str) -> list[SourceResult]:
        """Parse plain-text tool output into a single SourceResult."""
        if not raw or len(raw) < _MIN_PLAIN_OUTPUT_LENGTH:
            return []
        return [
            SourceResult(
                content=raw[:2000],
                source_ref=source_label,
                source_name="web_search",
            )
        ]
