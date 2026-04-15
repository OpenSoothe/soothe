"""Academic and encyclopedic InformationSource wrapping arxiv and wikipedia."""

from __future__ import annotations

import logging
from typing import Any

from soothe_daemon.subagents.research.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_KEYWORD_MATCH_THRESHOLD = 0.15


class AcademicSource:
    """Information source backed by academic and encyclopedic databases.

    Wraps langchain ``ArxivQueryRun`` and ``WikipediaQueryRun``.
    Chooses between them based on query heuristics.

    Args:
        enable_arxiv: Enable ArXiv search (default True).
        enable_wikipedia: Enable Wikipedia lookup (default True).
    """

    def __init__(
        self,
        *,
        enable_arxiv: bool = True,
        enable_wikipedia: bool = True,
    ) -> None:
        """Initialize the academic source with arxiv and/or wikipedia."""
        self._enable_arxiv = enable_arxiv
        self._enable_wikipedia = enable_wikipedia
        self._arxiv_tool: Any | None = None
        self._wikipedia_tool: Any | None = None
        self._tools_loaded = False

    def _ensure_tools(self) -> None:
        if self._tools_loaded:
            return
        self._tools_loaded = True

        if self._enable_arxiv:
            try:
                from langchain_community.tools import ArxivQueryRun

                self._arxiv_tool = ArxivQueryRun()
            except Exception:
                logger.debug("ArXiv tool not available", exc_info=True)

        if self._enable_wikipedia:
            try:
                from langchain_community.tools import WikipediaQueryRun
                from langchain_community.utilities import WikipediaAPIWrapper

                self._wikipedia_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
            except Exception:
                logger.debug("Wikipedia tool not available", exc_info=True)

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "academic"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "academic"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Query academic/encyclopedic sources.

        If the query looks academic, arxiv is tried first.  Wikipedia is
        used for encyclopedic or definitional queries.

        Args:
            query: Search query.
            context: Current research context.

        Returns:
            List of SourceResult from academic sources.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        q_lower = query.lower()
        is_academic = self._is_academic_query(q_lower)
        is_encyclopedic = self._is_encyclopedic_query(q_lower)

        if is_academic and self._arxiv_tool:
            try:
                raw = await self._arxiv_tool._arun(query)
                if raw and "No good" not in raw:
                    results.append(
                        SourceResult(
                            content=raw[:3000],
                            source_ref="arxiv",
                            source_name="academic",
                            metadata={"sub_source": "arxiv"},
                        )
                    )
            except Exception:
                logger.debug("ArXiv query failed for: %s", query, exc_info=True)

        if (is_encyclopedic or not results) and self._wikipedia_tool:
            try:
                raw = await self._wikipedia_tool._arun(query)
                if raw and "No good" not in raw:
                    results.append(
                        SourceResult(
                            content=raw[:3000],
                            source_ref="wikipedia",
                            source_name="academic",
                            metadata={"sub_source": "wikipedia"},
                        )
                    )
            except Exception:
                logger.debug("Wikipedia query failed for: %s", query, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for academic/encyclopedic queries."""
        from ._scoring import (
            _ACADEMIC_KEYWORDS,
            _ENCYCLOPEDIC_KEYWORDS,
            keyword_score,
        )

        q_lower = query.lower()
        acad = keyword_score(q_lower, _ACADEMIC_KEYWORDS, weight=0.2)
        ency = keyword_score(q_lower, _ENCYCLOPEDIC_KEYWORDS, weight=0.2)

        score = max(acad, ency)
        return min(1.0, max(0.05, score))

    # -- Heuristics ----------------------------------------------------------

    @staticmethod
    def _is_academic_query(q: str) -> bool:
        from ._scoring import _ACADEMIC_KEYWORDS, keyword_score

        return keyword_score(q, _ACADEMIC_KEYWORDS, weight=0.2) > _KEYWORD_MATCH_THRESHOLD

    @staticmethod
    def _is_encyclopedic_query(q: str) -> bool:
        from ._scoring import _ENCYCLOPEDIC_KEYWORDS, keyword_score

        return keyword_score(q, _ENCYCLOPEDIC_KEYWORDS, weight=0.2) > _KEYWORD_MATCH_THRESHOLD
