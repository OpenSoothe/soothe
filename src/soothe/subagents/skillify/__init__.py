"""Skillify subagent -- skill warehouse indexing and semantic retrieval (RFC-0004).

Provides two runtime concerns:
  1. Background indexing loop (asyncio.Task) that keeps the vector index in
     sync with the skill warehouse.
  2. Retrieval CompiledSubAgent (LangGraph) that serves on-demand skill
     bundles for user goals or downstream agents like Weaver.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.core.event_catalog import (
    SkillifyIndexingPendingEvent,
    SkillifyRetrieveCompletedEvent,
    SkillifyRetrieveNotReadyEvent,
    SkillifyRetrieveStartedEvent,
)
from soothe.subagents.skillify.indexer import SkillIndexer
from soothe.subagents.skillify.retriever import SkillRetriever
from soothe.subagents.skillify.warehouse import SkillWarehouse

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

    from soothe.subagents.skillify.models import SkillBundle

logger = logging.getLogger(__name__)

SKILLIFY_DESCRIPTION = (
    "Skill retrieval agent for semantic search over the skill warehouse. "
    "Given a task description or objective, returns a ranked bundle of relevant "
    "skills with paths and relevance scores. Use when you need to find skills "
    "matching a specific capability or goal."
)


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe.utils.progress import emit_progress

    emit_progress(event, logger)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class SkillifyState(dict):
    """State for the Skillify retrieval graph."""

    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _build_skillify_graph(retriever: SkillRetriever) -> Any:
    """Build and compile the Skillify retrieval LangGraph.

    Args:
        retriever: Configured SkillRetriever instance.

    Returns:
        Compiled LangGraph runnable.
    """

    async def _retrieve_async(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        query = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                query = msg.content if hasattr(msg, "content") else str(msg)
                break
        if not query and messages:
            last = messages[-1]
            query = last.content if hasattr(last, "content") else str(last)

        if not retriever.is_ready:
            _emit_progress(SkillifyIndexingPendingEvent(query=query[:200]).to_dict())

        _emit_progress(SkillifyRetrieveStartedEvent(query=query[:200]).to_dict())

        bundle: SkillBundle = await retriever.retrieve(query)

        if bundle.query.startswith("[Indexing in progress]"):
            _emit_progress(SkillifyRetrieveNotReadyEvent(message=bundle.query).to_dict())
            return {"messages": [AIMessage(content=bundle.query)]}

        top_score = bundle.results[0].score if bundle.results else 0.0
        _emit_progress(
            SkillifyRetrieveCompletedEvent(
                query=query[:200],
                result_count=len(bundle.results),
                top_score=round(top_score, 3),
            ).to_dict()
        )

        result_lines = [f"Found {len(bundle.results)} relevant skills (total indexed: {bundle.total_indexed}):\n"]
        for i, sr in enumerate(bundle.results, 1):
            result_lines.append(
                f"{i}. **{sr.record.name}** (score: {sr.score:.3f})\n"
                f"   Path: {sr.record.path}\n"
                f"   Description: {sr.record.description[:200]}\n"
                f"   Tags: {', '.join(sr.record.tags) if sr.record.tags else 'none'}"
            )

        result_text = "\n".join(result_lines)
        return {"messages": [AIMessage(content=result_text)]}

    def retrieve_sync(state: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper -- deepagents calls graph nodes in a thread pool."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(_retrieve_async(state))
            finally:
                new_loop.close()
        else:
            return loop.run_until_complete(_retrieve_async(state))

    graph = StateGraph(SkillifyState)
    graph.add_node("retrieve", retrieve_sync)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_skillify_subagent(
    _model: str | BaseChatModel | None = None,
    *,
    config: Any | None = None,
    **_kwargs: Any,
) -> CompiledSubAgent:
    """Create a Skillify subagent (CompiledSubAgent with background indexer).

    The indexer runs as a background ``asyncio.Task``. The returned
    ``CompiledSubAgent`` dict includes a ``_skillify_indexer`` key for
    external lifecycle management (call ``indexer.stop()`` on shutdown).

    Args:
        model: Unused (Skillify does not need an LLM). Accepted for
            interface consistency with other subagent factories.
        config: ``SootheConfig`` instance for warehouse paths, vector store,
            and embedding model resolution.
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        ``CompiledSubAgent`` dict compatible with deepagents.
    """
    from soothe.safety.config_driven import ConfigDrivenPolicy
    from soothe.config import SOOTHE_HOME, SootheConfig

    cfg: SootheConfig = config if isinstance(config, SootheConfig) else SootheConfig()

    default_warehouse = str(Path(SOOTHE_HOME) / "agents" / "skillify" / "warehouse")
    warehouse_paths = list(cfg.skillify.warehouse_paths) if hasattr(cfg, "skillify") else []
    if default_warehouse not in warehouse_paths:
        warehouse_paths.insert(0, default_warehouse)

    skillify_cfg = cfg.skillify if hasattr(cfg, "skillify") else None

    warehouse = SkillWarehouse(paths=warehouse_paths)

    vector_store, embeddings = _resolve_dependencies(cfg, skillify_cfg)

    collection = getattr(skillify_cfg, "index_collection", "soothe_skillify") if skillify_cfg else "soothe_skillify"
    interval = getattr(skillify_cfg, "index_interval_seconds", 300) if skillify_cfg else 300
    top_k = getattr(skillify_cfg, "retrieval_top_k", 10) if skillify_cfg else 10

    indexer = SkillIndexer(
        warehouse=warehouse,
        vector_store=vector_store,
        embeddings=embeddings,
        interval_seconds=interval,
        collection=collection,
        embedding_dims=cfg.embedding_dims,
        event_callback=_emit_progress,
    )

    retriever = SkillRetriever(
        vector_store=vector_store,
        embeddings=embeddings,
        top_k=top_k,
        ready_event=indexer.ready_event,
        policy=ConfigDrivenPolicy(),
        policy_profile=cfg.protocols.policy.profile,
    )

    _start_background_indexer(indexer)

    runnable = _build_skillify_graph(retriever)

    spec: CompiledSubAgent = {
        "name": "skillify",
        "description": SKILLIFY_DESCRIPTION,
        "runnable": runnable,
    }
    spec["_skillify_indexer"] = indexer  # type: ignore[typeddict-unknown-key]
    spec["_skillify_retriever"] = retriever  # type: ignore[typeddict-unknown-key]
    return spec


def _resolve_dependencies(
    cfg: Any,
    _skillify_cfg: Any,
) -> tuple[Any, Any]:
    """Resolve VectorStore and Embeddings from config."""
    # Use the vector store assigned to the 'skillify' role
    vs = cfg.create_vector_store_for_role("skillify")

    # Return a factory function to create fresh embedding instances
    embeddings_factory = cfg.create_embedding_model
    return vs, embeddings_factory


def _start_background_indexer(indexer: SkillIndexer) -> None:
    """Start the indexer background loop, creating an event loop if needed."""
    try:
        loop = asyncio.get_running_loop()
        indexer._start_task = loop.create_task(indexer.start())
    except RuntimeError:
        pass
