"""academic_research subagent factory."""

from __future__ import annotations

import logging
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .engine import build_academic_research_engine
from .protocol import AcademicResearchConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


class AcademicResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    research_topic: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


def _build_academic_source(config: SootheConfig) -> Any:
    from .sources.academic_search import AcademicSearchSource

    return AcademicSearchSource(config=config)


def create_academic_research_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create academic_research academic literature research subagent."""
    effort = context.get("effort")
    academic_source = _build_academic_source(config)
    sub_cfg = config.subagents.get("academic_research")
    extra = dict(sub_cfg.config) if sub_cfg else {}
    if effort is not None:
        extra["effort"] = effort
    ar_config = AcademicResearchConfig(**extra)

    synthesis_model = model
    synthesis_role = ar_config.synthesis_role
    if synthesis_role and synthesis_role != ar_config.llm_role:
        try:
            synthesis_model = config.create_chat_model(synthesis_role)
        except Exception:
            logger.warning(
                "academic_research synthesis_role %r unavailable, using primary model",
                synthesis_role,
                exc_info=True,
            )

    runnable = build_academic_research_engine(
        model,
        academic_source,
        ar_config,
        synthesis_model=synthesis_model,
        soothe_config=config,
    )

    return {
        "name": "academic_research",
        "description": (
            "academic_research: iterative academic literature research with URL crawling and "
            "adaptive report generation. Use for papers, literature reviews, citations, and "
            "method comparisons. Do NOT use for local codebase files or general web news "
            "(use deep_research)."
        ),
        "runnable": runnable,
    }
