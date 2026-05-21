"""Academic InformationSource wrapping DeepXiv SDK.

Provides semantic paper search across arXiv, bioRxiv, medRxiv, and PubMed Central
with AI-generated TLDRs and progressive content loading.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.subagents.research.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_KEYWORD_MATCH_THRESHOLD = 0.15


class AcademicSource:
    """Information source backed by DeepXiv academic databases.

    Wraps DeepXiv SDK Reader for semantic paper search across multiple
    academic repositories (arXiv, bioRxiv, medRxiv, PubMed Central).

    Args:
        config: Optional Soothe config for DeepXiv settings.
    """

    def __init__(
        self,
        config: Any | None = None,
    ) -> None:
        """Initialize the academic source with optional config."""
        self._config = config
        self._deepxiv_tool: Any | None = None
        self._tools_loaded = False

    def _ensure_tools(self) -> None:
        """Lazy-load DeepXiv search tool."""
        if self._tools_loaded:
            return
        self._tools_loaded = True

        try:
            from soothe.toolkits.deepxiv import DeepxivSearchTool

            deepxiv_config: dict[str, Any] = {}
            if self._config and hasattr(self._config, "tools"):
                dx = getattr(self._config.tools, "deepxiv", None)
                if dx:
                    deepxiv_config = {
                        "token": dx.token if hasattr(dx, "token") else None,
                        "timeout": dx.timeout if hasattr(dx, "timeout") else 60,
                        "max_retries": dx.max_retries if hasattr(dx, "max_retries") else 3,
                    }

            self._deepxiv_tool = DeepxivSearchTool(**deepxiv_config)
        except Exception:
            logger.debug("DeepXiv tool not available", exc_info=True)

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
        """Query academic sources using DeepXiv.

        Performs semantic paper search and returns formatted results
        with paper metadata and TLDR summaries.

        Args:
            query: Search query.
            context: Current research context.

        Returns:
            List of SourceResult from academic sources.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        if not self._deepxiv_tool:
            return results

        q_lower = query.lower()
        is_academic = self._is_academic_query(q_lower)

        if is_academic:
            try:
                raw = await self._deepxiv_tool._arun(query=query, size=5)
                if raw and not raw.startswith("Error"):
                    results.append(
                        SourceResult(
                            content=raw[:4000],
                            source_ref="deepxiv",
                            source_name="academic",
                            metadata={"sub_source": "deepxiv"},
                        )
                    )
            except Exception:
                logger.debug("DeepXiv query failed for: %s", query, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for academic queries."""
        from ._scoring import _ACADEMIC_KEYWORDS, keyword_score

        q_lower = query.lower()
        acad = keyword_score(q_lower, _ACADEMIC_KEYWORDS, weight=0.2)

        return min(1.0, max(0.05, acad))

    # -- Heuristics ----------------------------------------------------------

    @staticmethod
    def _is_academic_query(q: str) -> bool:
        from ._scoring import _ACADEMIC_KEYWORDS, keyword_score

        return keyword_score(q, _ACADEMIC_KEYWORDS, weight=0.2) > _KEYWORD_MATCH_THRESHOLD
