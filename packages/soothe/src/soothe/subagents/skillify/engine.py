"""Skillify retrieval LangGraph."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .events import (
    SkillifyCompletedEvent,
    SkillifyDispatchedEvent,
    SkillifyIndexingPendingEvent,
    SkillifyRetrieveCompletedEvent,
    SkillifyRetrieveNotReadyEvent,
    SkillifyRetrieveStartedEvent,
)
from .models import SkillBundle

if TYPE_CHECKING:
    from .retriever import SkillRetriever

logger = logging.getLogger(__name__)


class SkillifyState(TypedDict):
    messages: Annotated[list[Any], add_messages]


def _emit_event(event_dict: dict[str, Any]) -> None:
    event_type = event_dict.get("type", "unknown")
    logger.info("[%s] %s", event_type, event_dict)


def build_skillify_graph(retriever: SkillRetriever) -> Any:
    """Build and compile the Skillify retrieval graph."""

    async def _retrieve_async(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        query = ""
        for message in reversed(messages):
            if hasattr(message, "type") and message.type == "human":
                query = message.content if hasattr(message, "content") else str(message)
                break
        if not query and messages:
            last = messages[-1]
            query = last.content if hasattr(last, "content") else str(last)

        _emit_event(SkillifyDispatchedEvent(task=query[:200]).to_dict())

        if not retriever.is_ready:
            _emit_event(SkillifyIndexingPendingEvent(query=query[:200]).to_dict())

        _emit_event(SkillifyRetrieveStartedEvent(query=query[:200]).to_dict())

        bundle: SkillBundle = await retriever.retrieve(query)

        if bundle.query.startswith("[Indexing in progress]"):
            _emit_event(SkillifyRetrieveNotReadyEvent(message=bundle.query).to_dict())
            _emit_event(SkillifyCompletedEvent(duration_ms=0, result_count=0).to_dict())
            return {"messages": [AIMessage(content=bundle.query)]}

        top_score = bundle.results[0].score if bundle.results else 0.0
        _emit_event(
            SkillifyRetrieveCompletedEvent(
                query=query[:200],
                result_count=len(bundle.results),
                top_score=round(top_score, 3),
            ).to_dict()
        )

        result_lines = [
            f"Found {len(bundle.results)} relevant skills (total indexed: {bundle.total_indexed}):\n"
        ]
        for index, search_result in enumerate(bundle.results, 1):
            record = search_result.record
            result_lines.append(
                f"{index}. **{record.name}** (score: {search_result.score:.3f})\n"
                f"   Path: {record.path}\n"
                f"   Description: {record.description[:200]}\n"
                f"   Tags: {', '.join(record.tags) if record.tags else 'none'}"
            )

        result_text = "\n".join(result_lines)
        _emit_event(
            SkillifyCompletedEvent(duration_ms=0, result_count=len(bundle.results)).to_dict()
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
        return loop.run_until_complete(_retrieve_async(state))

    graph = StateGraph(SkillifyState)
    graph.add_node("retrieve", retrieve_sync)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", END)
    return graph.compile()
