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
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from soothe_sdk.plugin import plugin, subagent

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


def _emit_event(event_dict: dict[str, Any], ctx_logger: logging.Logger) -> None:
    """Emit progress event via logger or event emission.

    For community plugins, we use logger.info() for visibility.
    Daemon may intercept and convert to progress events.
    """
    event_type = event_dict.get("type", "unknown")
    ctx_logger.info(f"[{event_type}] {event_dict}")


class SkillifyState(TypedDict):
    """State for the Skillify retrieval graph."""

    messages: Annotated[list[Any], add_messages]


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

        _emit_event(SkillifyDispatchedEvent(task=query[:200]).to_dict(), logger)

        if not retriever.is_ready:
            _emit_event(SkillifyIndexingPendingEvent(query=query[:200]).to_dict(), logger)

        _emit_event(SkillifyRetrieveStartedEvent(query=query[:200]).to_dict(), logger)

        bundle: SkillBundle = await retriever.retrieve(query)

        if bundle.query.startswith("[Indexing in progress]"):
            _emit_event(SkillifyRetrieveNotReadyEvent(message=bundle.query).to_dict(), logger)
            _emit_event(SkillifyCompletedEvent(duration_ms=0, result_count=0).to_dict(), logger)
            return {"messages": [AIMessage(content=bundle.query)]}

        top_score = bundle.results[0].score if bundle.results else 0.0
        _emit_event(
            SkillifyRetrieveCompletedEvent(
                query=query[:200],
                result_count=len(bundle.results),
                top_score=round(top_score, 3),
            ).to_dict(),
            logger,
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
        _emit_event(
            SkillifyCompletedEvent(
                duration_ms=0,
                result_count=len(bundle.results),
            ).to_dict(),
            logger,
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


def _resolve_dependencies(soothe_cfg: Any) -> tuple[Any, Any]:
    """Resolve VectorStore and Embeddings from context services."""
    # Use context services if available
    if hasattr(soothe_cfg, "services"):
        services = soothe_cfg.services
        vector_store = services.get("vector_store")
        embeddings_factory = services.get("embeddings_factory")
        if vector_store and embeddings_factory:
            return vector_store, embeddings_factory

    # Fallback: use soothe_config protocol methods
    if hasattr(soothe_cfg, "create_vector_store_for_role"):
        vs = soothe_cfg.create_vector_store_for_role("skillify")
        embeddings_factory = soothe_cfg.create_embedding_model
        return vs, embeddings_factory

    # Last resort: create basic implementations
    msg = "Cannot resolve vector_store or embeddings from context or config"
    raise ValueError(msg)


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
        import soothe_plugins.skillify.events  # noqa: F401

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
            config: Plugin context (PluginContext instance from soothe_sdk).
            context: Plugin context (same as config parameter - deprecated parameter name).
            **_kwargs: Additional config (ignored).

        Returns:
            CompiledSubAgent dict with background indexer.
        """

        soothe_cfg = context.soothe_config
        plugin_cfg = context.config if hasattr(context, "config") else {}
        ctx_logger = context.logger if hasattr(context, "logger") else logger

        # Get plugin-specific config
        skillify_cfg = plugin_cfg.get("skillify", {})

        # Resolve warehouse paths
        soothe_home = Path.home() / ".soothe"  # Default SOOTHE_HOME
        if hasattr(soothe_cfg, "home"):
            soothe_home = Path(soothe_cfg.home)

        default_warehouse = str(soothe_home / "agents" / "skillify" / "warehouse")
        warehouse_paths = skillify_cfg.get("warehouse_paths", [])
        if isinstance(warehouse_paths, list) and default_warehouse not in warehouse_paths:
            warehouse_paths.insert(0, default_warehouse)

        warehouse = SkillWarehouse(paths=warehouse_paths)
        vector_store, embeddings = _resolve_dependencies(soothe_cfg)

        # Extract config parameters with defaults
        collection = skillify_cfg.get("index_collection", "soothe_skillify")
        interval = skillify_cfg.get("index_interval_seconds", 300)
        top_k = skillify_cfg.get("retrieval_top_k", 10)
        embedding_dims = skillify_cfg.get("embedding_dims", 1536)

        def emit_callback(event: dict[str, Any]) -> None:
            _emit_event(event, ctx_logger)

        self._indexer = SkillIndexer(
            warehouse=warehouse,
            vector_store=vector_store,
            embeddings=embeddings,
            interval_seconds=interval,
            collection=collection,
            embedding_dims=embedding_dims,
            event_callback=emit_callback,
        )

        retriever = SkillRetriever(
            vector_store=vector_store,
            embeddings=embeddings,
            top_k=top_k,
            ready_event=self._indexer.ready_event,
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
