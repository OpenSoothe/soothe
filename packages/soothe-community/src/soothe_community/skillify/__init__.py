"""Skillify subagent plugin -- skill warehouse indexing and semantic retrieval (RFC-0004).

Community plugin for Soothe that provides:
  1. Background indexing loop (asyncio.Task) keeping the vector index in sync
     with the skill warehouse.
  2. Retrieval CompiledSubAgent (LangGraph) serving on-demand skill bundles
     for user goals or downstream agents like Weaver.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from soothe_sdk import plugin, subagent

from .events import (
    SkillifyCompletedEvent,
    SkillifyDispatchedEvent,
    SkillifyIndexingPendingEvent,
    SkillifyRetrieveCompletedEvent,
    SkillifyRetrieveNotReadyEvent,
    SkillifyRetrieveStartedEvent,
)
from .indexer import SkillIndexer
from .retriever import SkillRetriever
from .warehouse import SkillWarehouse

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

    from .models import SkillBundle

logger = logging.getLogger(__name__)

SKILLIFY_DESCRIPTION = (
    "Skill retrieval agent for semantic search over the skill warehouse. "
    "Given a task description or objective, returns a ranked bundle of relevant "
    "skills with paths and relevance scores. Use when you need to find skills "
    "matching a specific capability or goal."
)


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe.utils.progress import emit_progress

    emit_progress(event, logger)


class SkillifyState(dict):
    """State for the Skillify retrieval graph."""

    messages: Annotated[list, add_messages]


def _build_skillify_graph(retriever: SkillRetriever) -> Any:
    """Build and compile the Skillify retrieval LangGraph."""

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

        _emit_progress(SkillifyDispatchedEvent(task=query[:200]).to_dict())

        if not retriever.is_ready:
            _emit_progress(SkillifyIndexingPendingEvent(query=query[:200]).to_dict())

        _emit_progress(SkillifyRetrieveStartedEvent(query=query[:200]).to_dict())

        bundle: SkillBundle = await retriever.retrieve(query)

        if bundle.query.startswith("[Indexing in progress]"):
            _emit_progress(SkillifyRetrieveNotReadyEvent(message=bundle.query).to_dict())
            _emit_progress(SkillifyCompletedEvent(duration_ms=0, result_count=0).to_dict())
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
        _emit_progress(
            SkillifyCompletedEvent(
                duration_ms=0,
                result_count=len(bundle.results),
            ).to_dict()
        )
        return {"messages": [AIMessage(content=result_text)]}

    def retrieve_sync(state: dict[str, Any]) -> dict[str, Any]:
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


def _resolve_dependencies(cfg: Any, _skillify_cfg: Any) -> tuple[Any, Any]:
    """Resolve VectorStore and Embeddings from config."""
    vs = cfg.create_vector_store_for_role("skillify")
    embeddings_factory = cfg.create_embedding_model
    return vs, embeddings_factory


def _start_background_indexer(indexer: SkillIndexer) -> None:
    """Start the indexer background loop, creating an event loop if needed."""
    try:
        loop = asyncio.get_running_loop()
        indexer._start_task = loop.create_task(indexer.start())
    except RuntimeError:
        pass


@plugin(
    name="skillify",
    version="1.0.0",
    description="Skill warehouse indexing and semantic retrieval",
    dependencies=["langgraph>=0.2.0"],
    trust_level="standard",
)
class SkillifyPlugin:
    """Skillify community plugin for skill warehouse indexing and retrieval."""

    def __init__(self) -> None:
        self._indexer: SkillIndexer | None = None

    async def on_load(self, context: Any) -> None:
        """Trigger event self-registration."""
        import soothe_community.skillify.events  # noqa: F401

        context.logger.info("Skillify plugin loaded")

    async def on_unload(self) -> None:
        """Stop the background indexer."""
        if self._indexer is not None:
            try:
                await self._indexer.stop()
            except Exception:
                pass
            self._indexer = None

    @subagent(
        name="skillify",
        description=SKILLIFY_DESCRIPTION,
    )
    async def create_skillify(
        self,
        model: str | BaseChatModel | None,
        config: Any,
        context: Any,
        **_kwargs: Any,
    ) -> CompiledSubAgent:
        """Create a Skillify subagent.

        Args:
            model: Unused (Skillify does not need an LLM).
            config: SootheConfig instance.
            context: Plugin context.
            **_kwargs: Additional config (ignored).

        Returns:
            CompiledSubAgent dict with background indexer.
        """
        from soothe.config import SOOTHE_HOME, SootheConfig
        from soothe.core.config_driven import ConfigDrivenPolicy

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

        self._indexer = SkillIndexer(
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
            ready_event=self._indexer.ready_event,
            policy=ConfigDrivenPolicy(),
            policy_profile=cfg.protocols.policy.profile,
        )

        _start_background_indexer(self._indexer)

        runnable = _build_skillify_graph(retriever)

        spec: CompiledSubAgent = {
            "name": "skillify",
            "description": SKILLIFY_DESCRIPTION,
            "runnable": runnable,
        }
        spec["_skillify_indexer"] = self._indexer  # type: ignore[typeddict-unknown-key]
        spec["_skillify_retriever"] = retriever  # type: ignore[typeddict-unknown-key]
        return spec

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions."""
        return [self.create_skillify]
