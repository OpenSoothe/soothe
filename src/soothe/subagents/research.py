"""Research subagent -- iterative web research specialist.

Implements an iterative research loop:
  query generation -> web search -> reflection -> synthesis with citations.
"""

from __future__ import annotations

import datetime
import json
import logging
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe.utils.progress import emit_progress

    emit_progress(event, logger)


# ---------------------------------------------------------------------------
# State schemas
# ---------------------------------------------------------------------------


class ResearchState(dict):
    """Top-level state for the research graph."""

    messages: Annotated[list, add_messages]
    research_topic: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_research_loops: int
    research_loop_count: int


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

QUERY_WRITER_INSTRUCTIONS = """\
Generate sophisticated web search queries for research.

Instructions:
- Prefer a single query; add more only if the topic has multiple independent aspects.
- Each query should be LESS than 40 characters.
- Queries in the same language as the original topic.
- The current date is {current_date}.

Format your response as JSON: {{"rationale": "...", "query": ["..."]}}

Topic: {research_topic}"""

REFLECTION_INSTRUCTIONS = """\
You are an expert research assistant analysing summaries about "{research_topic}".

- Identify knowledge gaps and generate follow-up queries (1-3).
- If summaries are sufficient, set is_sufficient to true.
- Follow-up queries should be < 40 characters, same language as the topic.

Format as JSON:
{{"is_sufficient": true/false, "knowledge_gap": "...", "follow_up_queries": ["..."]}}

Summaries:
{summaries}"""

ANSWER_INSTRUCTIONS = """\
Generate a high-quality answer based on the provided research summaries.

- The current date is {current_date}.
- Include all citations from summaries.
- Structure the answer logically and comprehensively.
- Include specific details, facts, and current information.

Topic: {research_topic}

Summaries:
{summaries}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_research_topic(state: dict[str, Any]) -> str:
    """Extract the research topic from state or messages."""
    if "research_topic" in state:
        return state["research_topic"]
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            return msg.content if hasattr(msg, "content") else str(msg)
    if messages:
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)
    return ""


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _generate_query(state: dict[str, Any], model: BaseChatModel) -> dict[str, Any]:
    """Generate initial search queries from the research topic."""
    research_topic = _extract_research_topic(state)
    _emit_progress(
        {
            "type": "soothe.research.generate_query",
            "topic": research_topic[:200],
        }
    )

    prompt = QUERY_WRITER_INSTRUCTIONS.format(
        current_date=datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d"),
        research_topic=research_topic,
    )
    resp = model.invoke([{"role": "user", "content": prompt}])
    content = str(resp.content)

    try:
        parsed = json.loads(content)
        queries = parsed.get("query", [content])
    except json.JSONDecodeError:
        queries = [content.strip()]

    _emit_progress(
        {
            "type": "soothe.research.queries_generated",
            "queries": queries,
        }
    )
    return {"queries": queries}


def _web_research(state: dict[str, Any], search_tool: Any) -> dict[str, Any]:
    """Execute a single web search query and summarise results."""
    query = state.get("search_query", "")
    _emit_progress(
        {
            "type": "soothe.research.web_search",
            "query": query,
        }
    )

    try:
        results = search_tool.invoke(query)
        summary = str(results) if results else f"No results for: {query}"
    except Exception:
        logger.exception("Search failed for query: %s", query)
        summary = f"Search failed for: {query}"

    _emit_progress(
        {
            "type": "soothe.research.search_done",
            "query": query,
            "result_length": len(summary),
        }
    )
    return {"summary": summary, "query": query}


def _reflect(state: dict[str, Any], model: BaseChatModel) -> dict[str, Any]:
    """Reflect on gathered summaries and decide whether to continue."""
    research_topic = _extract_research_topic(state)
    loop_count = state.get("research_loop_count", 0)
    num_summaries = len(state.get("search_summaries", []))

    _emit_progress(
        {
            "type": "soothe.research.reflect",
            "loop": loop_count + 1,
            "summaries_so_far": num_summaries,
        }
    )

    summaries = "\n\n".join(state.get("search_summaries", []))
    prompt = REFLECTION_INSTRUCTIONS.format(
        research_topic=research_topic,
        summaries=summaries or "(no summaries yet)",
    )
    resp = model.invoke([{"role": "user", "content": prompt}])
    content = str(resp.content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"is_sufficient": True, "knowledge_gap": "", "follow_up_queries": []}

    is_sufficient = parsed.get("is_sufficient", True)
    follow_ups = parsed.get("follow_up_queries", [])

    _emit_progress(
        {
            "type": "soothe.research.reflection_done",
            "loop": loop_count + 1,
            "is_sufficient": is_sufficient,
            "follow_up_queries": follow_ups,
        }
    )

    return {
        "is_sufficient": is_sufficient,
        "follow_up_queries": follow_ups,
    }


def _finalize_answer(state: dict[str, Any], model: BaseChatModel) -> dict[str, Any]:
    """Synthesise the final answer from all summaries."""
    research_topic = _extract_research_topic(state)
    num_summaries = len(state.get("search_summaries", []))
    num_sources = len(state.get("sources_gathered", []))

    _emit_progress(
        {
            "type": "soothe.research.synthesize",
            "topic": research_topic[:200],
            "total_summaries": num_summaries,
            "total_sources": num_sources,
        }
    )

    summaries = "\n\n".join(state.get("search_summaries", []))
    prompt = ANSWER_INSTRUCTIONS.format(
        current_date=datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d"),
        research_topic=research_topic,
        summaries=summaries,
    )
    resp = model.invoke([{"role": "user", "content": prompt}])
    answer = str(resp.content)

    _emit_progress(
        {
            "type": "soothe.research.complete",
            "answer_length": len(answer),
        }
    )
    return {"answer": answer}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _build_research_graph(
    model: BaseChatModel,
    search_tool: Any,
    max_loops: int = 2,
) -> Any:
    """Build and compile the research LangGraph.

    Args:
        model: LLM for query generation, reflection, and answer synthesis.
        search_tool: A langchain `BaseTool` for web search (e.g. TavilySearch).
        max_loops: Maximum research reflection loops.

    Returns:
        Compiled LangGraph runnable.
    """

    def generate_query_node(state: dict[str, Any]) -> dict[str, Any]:
        result = _generate_query(state, model)
        return {
            "search_summaries": [],
            "sources_gathered": [],
            "research_loop_count": 0,
            "_queries": result["queries"],
        }

    def route_to_search(state: dict[str, Any]) -> list[Send]:
        queries = state.get("_queries", [])
        return [Send("web_research", {"search_query": q, **state}) for q in queries]

    def web_research_node(state: dict[str, Any]) -> dict[str, Any]:
        result = _web_research(state, search_tool)
        return {
            "search_summaries": [result["summary"]],
            "sources_gathered": [result["query"]],
        }

    def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
        result = _reflect(state, model)
        return {
            "research_loop_count": state.get("research_loop_count", 0) + 1,
            "_is_sufficient": result["is_sufficient"],
            "_follow_up_queries": result["follow_up_queries"],
        }

    def route_after_reflection(state: dict[str, Any]) -> list[Send] | str:
        if state.get("_is_sufficient") or state.get("research_loop_count", 0) >= max_loops:
            return "finalize_answer"
        follow_ups = state.get("_follow_up_queries", [])
        if follow_ups:
            return [Send("web_research", {"search_query": q, **state}) for q in follow_ups]
        return "finalize_answer"

    def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
        return _finalize_answer(state, model)

    graph = StateGraph(ResearchState)
    graph.add_node("generate_query", generate_query_node)
    graph.add_node("web_research", web_research_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("finalize_answer", finalize_node)

    graph.add_edge(START, "generate_query")
    graph.add_conditional_edges("generate_query", route_to_search, ["web_research"])
    graph.add_edge("web_research", "reflect")
    graph.add_conditional_edges("reflect", route_after_reflection, ["web_research", "finalize_answer"])
    graph.add_edge("finalize_answer", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

RESEARCH_DESCRIPTION = (
    "Deep research specialist for iterative web research. Generates search queries, "
    "performs multi-engine web search, reflects on knowledge gaps, and synthesises "
    "a comprehensive answer with citations. Use for questions requiring thorough "
    "research across multiple sources."
)


def _create_research_search_tool() -> Any:
    """Create the preferred search tool for the research workflow."""
    from soothe.tools.wizsearch import WizsearchSearchTool

    return WizsearchSearchTool(
        config={
            "default_engines": ["tavily"],
            "max_results_per_engine": 5,
        }
    )


def create_research_subagent(
    model: str | BaseChatModel | None = None,
    max_loops: int = 2,
    **_kwargs: object,
) -> CompiledSubAgent:
    """Create a Research subagent (CompiledSubAgent with LangGraph workflow).

    The search tool defaults to Soothe's `wizsearch_search` wrapper.
    If unavailable, it falls back to `DuckDuckGoSearchRun`.

    Args:
        model: LLM model string or instance.
        max_loops: Maximum research reflection loops.
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    import os

    from langchain.chat_models import init_chat_model

    if model is None:
        msg = (
            "Research subagent requires a model. Pass a model string "
            "(e.g. 'openai:qwen3.5-flash') or a BaseChatModel instance."
        )
        raise ValueError(msg)
    if isinstance(model, str):
        model_kwargs: dict[str, Any] = {}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            model_kwargs["base_url"] = base_url
            model_kwargs["use_responses_api"] = False
        resolved_model = init_chat_model(model, **model_kwargs)
    else:
        resolved_model = model

    try:
        search_tool = _create_research_search_tool()
    except ImportError:
        try:
            from langchain_community.tools import DuckDuckGoSearchRun

            search_tool = DuckDuckGoSearchRun()
        except ImportError:
            msg = "Research subagent requires a search tool. Install soothe[wizsearch] or duckduckgo-search."
            raise ImportError(msg) from None

    runnable = _build_research_graph(resolved_model, search_tool, max_loops=max_loops)

    return {
        "name": "research",
        "description": RESEARCH_DESCRIPTION,
        "runnable": runnable,
    }
