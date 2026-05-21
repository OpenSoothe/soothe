"""Academic paper search via DeepXiv."""

from __future__ import annotations

import logging
from typing import Any

from soothe.subagents.tacitus.json_util import compact_search_query
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_CAPABILITY_DESCRIPTION = (
    "Scientific papers, preprints, peer-reviewed research, citations, methods, "
    "and literature from arXiv, bioRxiv, medRxiv, and PubMed Central."
)


class AcademicSearchSource:
    """Semantic academic search (DeepxivSearchTool via DeepxivToolkit)."""

    capability_id: CapabilityId = "academic_search"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._deepxiv_tool: Any | None = None
        self._tools_loaded = False

    def _ensure_tools(self) -> None:
        if self._tools_loaded:
            return
        self._tools_loaded = True
        try:
            from soothe.toolkits.deepxiv import DeepxivToolkit

            deepxiv_kwargs: dict[str, Any] = {}
            if self._config and hasattr(self._config, "tools"):
                dx = getattr(self._config.tools, "deepxiv", None)
                if dx:
                    deepxiv_kwargs = {
                        "token": getattr(dx, "token", None),
                        "timeout": getattr(dx, "timeout", 60),
                        "max_retries": getattr(dx, "max_retries", 3),
                    }
            toolkit = DeepxivToolkit(**deepxiv_kwargs)
            for tool in toolkit.get_tools():
                if getattr(tool, "name", "") == "deepxiv_search":
                    self._deepxiv_tool = tool
                    break
        except Exception:
            logger.debug("DeepXiv toolkit not available", exc_info=True)

    @property
    def name(self) -> str:
        return "academic"

    @property
    def source_type(self) -> SourceType:
        return "academic"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        self._ensure_tools()
        if not self._deepxiv_tool:
            return []

        search_q = compact_search_query(query, max_len=200)
        try:
            raw = await self._deepxiv_tool._arun(query=search_q, size=5)
            if raw and not str(raw).startswith("Error"):
                return [
                    SourceResult(
                        content=str(raw)[:4000],
                        source_ref="deepxiv",
                        source_name="academic",
                        metadata={"sub_source": "deepxiv"},
                    )
                ]
        except Exception:
            logger.debug("DeepXiv query failed for: %s", search_q, exc_info=True)
        return []
