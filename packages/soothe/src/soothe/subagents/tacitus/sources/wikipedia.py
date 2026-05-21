"""Wikipedia encyclopedia capability."""

from __future__ import annotations

import logging

from soothe.subagents.tacitus.json_util import compact_search_query
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_CAPABILITY_DESCRIPTION = (
    "Encyclopedia articles, definitions, historical overviews, biographies, "
    "and conceptual background from Wikipedia."
)


class WikipediaSource:
    """Wikipedia via the ``wikipedia`` Python package (langchain fallback)."""

    capability_id: CapabilityId = "wikipedia"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self) -> None:
        self._langchain_tool: object | None = None
        self._langchain_tried = False

    def _ensure_langchain(self) -> None:
        if self._langchain_tried:
            return
        self._langchain_tried = True
        try:
            from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
            from langchain_community.utilities import WikipediaAPIWrapper

            self._langchain_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        except Exception:
            logger.debug("LangChain Wikipedia tool not available", exc_info=True)

    @staticmethod
    def _query_wikipedia_package(query: str) -> str | None:
        try:
            import wikipedia

            wikipedia.set_lang("zh" if any("\u4e00" <= c <= "\u9fff" for c in query) else "en")
            return wikipedia.summary(query, sentences=8, auto_suggest=True)
        except Exception:
            return None

    @property
    def name(self) -> str:
        return "wikipedia"

    @property
    def source_type(self) -> SourceType:
        return "encyclopedia"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        search_q = compact_search_query(query, max_len=80)

        raw = self._query_wikipedia_package(search_q)
        if raw:
            return [
                SourceResult(
                    content=raw[:3000],
                    source_ref="wikipedia",
                    source_name="wikipedia",
                    metadata={"sub_source": "wikipedia"},
                )
            ]

        self._ensure_langchain()
        if self._langchain_tool is not None:
            try:
                lc_raw = await self._langchain_tool._arun(search_q)  # type: ignore[union-attr]
                if lc_raw and "No good" not in lc_raw:
                    return [
                        SourceResult(
                            content=str(lc_raw)[:3000],
                            source_ref="wikipedia",
                            source_name="wikipedia",
                            metadata={"sub_source": "wikipedia_langchain"},
                        )
                    ]
            except Exception:
                logger.debug("LangChain Wikipedia failed for: %s", search_q, exc_info=True)

        return []
