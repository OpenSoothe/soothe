"""deep_research subagent factory."""

from __future__ import annotations

import logging
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .engine import build_deep_research_engine
from .protocol import DeepResearchConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


class DeepResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    research_topic: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


def _build_web_source(config: SootheConfig) -> Any:
    from .sources.web_search import WebSearchSource

    return WebSearchSource(config=config)


def create_deep_research_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create deep_research public web research subagent."""
    effort = context.get("effort")
    web_source = _build_web_source(config)
    sub_cfg = config.subagents.get("deep_research")
    extra = dict(sub_cfg.config) if sub_cfg else {}
    if effort is not None:
        extra["effort"] = effort
    dr_config = DeepResearchConfig(**extra)

    synthesis_model = model
    synthesis_role = dr_config.synthesis_role
    if synthesis_role and synthesis_role != dr_config.llm_role:
        try:
            synthesis_model = config.create_chat_model(synthesis_role)
        except Exception:
            logger.warning(
                "deep_research synthesis_role %r unavailable, using primary model",
                synthesis_role,
                exc_info=True,
            )

    runnable = build_deep_research_engine(
        model,
        web_source,
        dr_config,
        synthesis_model=synthesis_model,
        soothe_config=config,
    )

    return {
        "name": "deep_research",
        "description": (
            "deep_research: iterative public web research with URL crawling and adaptive "
            "report generation. Use for external facts, comparisons, how-tos, and industry "
            "landscape. Do NOT use for local codebase, repository files, or academic "
            "literature."
        ),
        "runnable": runnable,
    }
