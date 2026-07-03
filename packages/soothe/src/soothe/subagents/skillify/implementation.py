"""Skillify subagent factory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .engine import build_skillify_graph
from .runtime import get_skillify_retriever

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

SKILLIFY_DESCRIPTION = (
    "Skill retrieval agent for semantic search over the skill warehouse. "
    "Given a task description or objective, returns a ranked bundle of relevant "
    "skills with paths and relevance scores. Use when you need to find skills "
    "matching a specific capability or goal."
)


def create_skillify_subagent(
    model: BaseChatModel | None,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the Skillify ``CompiledSubAgent`` spec.

    Args:
        model: Unused — Skillify does not call an LLM.
        config: Soothe configuration (vector store, embeddings, subagent options).
        context: Resolver context; ``work_dir`` is accepted for parity with other subagents.

    Returns:
        Dict with ``name``, ``description``, and ``runnable`` graph.
    """
    del model, context

    def emit_callback(event: dict[str, Any]) -> None:
        event_type = event.get("type", "unknown")
        logger.info("[%s] %s", event_type, event)

    retriever = get_skillify_retriever(config, indexer_event_callback=emit_callback)
    if retriever is None:
        raise RuntimeError("Skillify subagent is enabled but retriever could not be created")

    runnable = build_skillify_graph(retriever)

    return {
        "name": "skillify",
        "description": SKILLIFY_DESCRIPTION,
        "runnable": runnable,
    }
