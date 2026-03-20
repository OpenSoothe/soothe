"""Web search InformationSource wrapping wizsearch and serper."""

from __future__ import annotations

import logging
from typing import Any

from soothe.inquiry.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_KEYWORD_MATCH_THRESHOLD = 0.3
_LOW_RELEVANCE_SCORE = 0.15
_CODE_PENALTY_SCORE = 0.25
_ACADEMIC_HINT_SCORE = 0.5
_DEFAULT_WEB_SCORE = 0.6
_MIN_RESULTS_FOR_SERPER_FALLBACK = 3
_MIN_RAW_LENGTH_FOR_FALLBACK = 50
_MIN_PLAIN_OUTPUT_LENGTH = 10


class WebSource:
    """Information source backed by multi-engine web search.

    Wraps ``WizsearchSearchTool`` (primary) with optional ``SerperSearchTool``
    fallback.  Results are normalised into ``SourceResult`` instances.

    Args:
        config: Optional Soothe config for wizsearch settings.
        enable_serper: Also query Serper if available (default False).
    """

    def __init__(
        self,
        config: Any | None = None,
        *,
        enable_serper: bool = False,
    ) -> None:
        """Initialize the web source with optional config and serper fallback."""
        self._config = config
        self._enable_serper = enable_serper
        self._search_tool: Any | None = None
        self._serper_tool: Any | None = None

    def _ensure_tools(self) -> None:
        if self._search_tool is not None:
            return
        from soothe.tools._internal.wizsearch import WizsearchSearchTool

        wizsearch_config: dict[str, Any] = {}
        if self._config and hasattr(self._config, "tools_settings"):
            ws = getattr(self._config.tools_settings, "wizsearch", None)
            if ws:
                wizsearch_config = {
                    "default_engines": ws.default_engines,
                    "max_results_per_engine": ws.max_results_per_engine,
                    "timeout": ws.timeout,
                }
        self._search_tool = WizsearchSearchTool(config=wizsearch_config)

        if self._enable_serper:
            try:
                from soothe.tools._internal.serper import SerperSearchTool

                self._serper_tool = SerperSearchTool()
            except Exception:
                logger.debug("Serper not available, using wizsearch only", exc_info=True)

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

        Args:
            query: Search query string.
            context: Current research context.

        Returns:
            List of SourceResult from web search engines.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        raw = await self._search_tool._arun(query=query)
        results.extend(self._parse_wizsearch_output(raw, query))

        if self._serper_tool and len(results) < _MIN_RESULTS_FOR_SERPER_FALLBACK:
            try:
                serper_raw = await self._serper_tool._arun(query=query)
                results.extend(self._parse_plain_output(serper_raw, "serper"))
            except Exception:
                logger.debug("Serper fallback failed", exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Web search is the default fallback -- always somewhat relevant."""
        from soothe.inquiry.sources._scoring import (
            _ACADEMIC_KEYWORDS,
            _CODE_KEYWORDS,
            has_file_path,
            keyword_score,
        )
        from soothe.inquiry.sources.filesystem import FilesystemSource

        if has_file_path(query) or FilesystemSource._looks_like_path(query.strip().split()[0] if query.strip() else ""):
            return _LOW_RELEVANCE_SCORE

        code_score = keyword_score(query, _CODE_KEYWORDS)
        if code_score > _KEYWORD_MATCH_THRESHOLD:
            return _CODE_PENALTY_SCORE

        academic_score = keyword_score(query, _ACADEMIC_KEYWORDS)
        if academic_score > _KEYWORD_MATCH_THRESHOLD:
            return _ACADEMIC_HINT_SCORE

        return _DEFAULT_WEB_SCORE

    # -- Parsing helpers -----------------------------------------------------

    @staticmethod
    def _parse_wizsearch_output(raw: str, query: str) -> list[SourceResult]:
        """Parse the structured wizsearch output into SourceResults."""
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
