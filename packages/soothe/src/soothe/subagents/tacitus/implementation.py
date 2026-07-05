"""Tacitus subagent factory."""

from __future__ import annotations

import logging
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .engine import build_tacitus_engine
from .protocol import TacitusConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_DOMAIN_ALIASES: dict[str, str] = {
    "auto": "public",
    "deep": "public",
    "code": "public",
    "web": "web",
    "academic": "academic",
    "public": "public",
}


class TacitusState(TypedDict):
    """State schema for Tacitus subagent."""

    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


def _normalize_domain(domain: str) -> str:
    key = (domain or "public").strip().lower()
    return _DOMAIN_ALIASES.get(key, "public")


def _build_public_sources(config: SootheConfig) -> list[Any]:
    from .sources import (
        AcademicSearchSource,
        UrlCrawlSource,
        WebSearchSource,
    )

    return [
        WebSearchSource(config=config),
        AcademicSearchSource(config=config),
        UrlCrawlSource(config=config),
    ]


def create_tacitus_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create Tacitus public-domain research subagent.

    The resolver supplies ``router.fast`` as ``model`` unless ``subagents.tacitus.model``
    is set explicitly. Loop steps use that model; final synthesis uses ``synthesis_role``
    (default ``think``).
    """
    domain = _normalize_domain(context.get("domain", "public"))
    effort = context.get("effort")

    sources = _build_public_sources(config)
    sub_cfg = config.subagents.get("tacitus")
    extra = dict(sub_cfg.config) if sub_cfg else {}
    if effort is not None:
        extra["effort"] = effort
    tacitus_config = TacitusConfig(**extra)

    fast_model = model
    synthesis_model = model
    synthesis_role = tacitus_config.synthesis_role
    if synthesis_role and synthesis_role != tacitus_config.llm_role:
        try:
            synthesis_model = config.create_chat_model(synthesis_role)
            logger.debug("Tacitus synthesis using role %s", synthesis_role)
        except Exception:
            logger.warning(
                "Tacitus synthesis_role %r unavailable, using primary model",
                synthesis_role,
                exc_info=True,
            )

    runnable = build_tacitus_engine(
        fast_model,
        sources,
        tacitus_config,
        synthesis_model=synthesis_model,
        soothe_config=config,
        _domain=domain,
    )

    return {
        "name": "tacitus",
        "description": (
            "Tacitus: deep public-domain research across web search, academic "
            "papers, and public URLs. Use for thorough investigation and cross-validation. "
            "Do not use for local codebase or file exploration."
        ),
        "runnable": runnable,
    }
