"""Research engine -- tool-agnostic iterative research loop.

Implements the research paradigm as a LangGraph:

  analyze_topic -> generate_queries -> [route_and_gather] ->
  summarize -> reflect -> [continue | synthesize] -> END

The engine is parameterised by a list of ``InformationSource``
instances and a ``SourceRouter``. It knows nothing about web_search,
file_edit, or any specific tool -- those details live in the sources.
"""

from __future__ import annotations

import asyncio
import atexit
import datetime
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from .events import (
    ResearchAnalyzeEvent,
    ResearchCompletedEvent,
    ResearchDispatchedEvent,
    ResearchGatherDoneEvent,
    ResearchGatherEvent,
    ResearchInternalLLMResponseEvent,
    ResearchJudgementEvent,
    ResearchQueriesGeneratedEvent,
    ResearchReflectEvent,
    ResearchReflectionDoneEvent,
    ResearchSubQuestionsEvent,
    ResearchSummarizeEvent,
    ResearchSynthesizeEvent,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from .protocol import InformationSource, ResearchConfig

logger = logging.getLogger(__name__)

# Module-level shared thread pool for async-to-sync conversion in research engine
# This prevents creating new thread pools for each query
_shared_pool: ThreadPoolExecutor | None = None


def _get_shared_pool() -> ThreadPoolExecutor:
    """Get or create the shared thread pool."""
    global _shared_pool
    if _shared_pool is None:
        _shared_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-async")
        atexit.register(_cleanup_pool)
    return _shared_pool


def _cleanup_pool() -> None:
    """Cleanup the shared thread pool on exit."""
    global _shared_pool
    if _shared_pool is not None:
        _shared_pool.shutdown(wait=True)
        _shared_pool = None


# ---------------------------------------------------------------------------
# Progress helper (mirrors research.py pattern)
# ---------------------------------------------------------------------------


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe_daemon.utils.progress import emit_progress

    emit_progress(event, logger)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class ResearchEngineState(dict):
    """Top-level state for the research engine graph."""

    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str  # source domain hint ("auto", "web", "code", "deep")
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_ANALYZE_TOPIC = """\
You are a research analyst. Analyse the following topic and identify the key \
sub-questions that need to be answered.  For each sub-question, indicate \
which information domain is most likely to have the answer.

Domains available: {domains}

Current date: {current_date}

Topic: {topic}

Respond as JSON:
{{"sub_questions": [
    {{"question": "...", "suggested_domain": "web|academic|filesystem|cli|browser|document"}}
]}}"""

_GENERATE_QUERIES = """\
Generate targeted search queries for the following sub-questions.
Each query should be concise (< 50 characters) and in the same language \
as the original topic.

Current date: {current_date}

Sub-questions:
{sub_questions}

Respond as JSON:
{{"queries": [
    {{"query": "...", "domain_hint": "web|academic|filesystem|cli|browser|document"}}
]}}"""

_SUMMARIZE = """\
Summarise the following raw results gathered from multiple sources for the \
topic "{topic}".  Preserve source references for citation.

Existing summaries so far:
{existing_summaries}

New results:
{new_results}

Provide a concise, integrated summary that adds to the existing knowledge."""

_REFLECT = """\
You are an expert research analyst evaluating gathered summaries about "{topic}".

- Identify knowledge gaps.
- If the summaries are sufficient to answer the original topic thoroughly, \
set is_sufficient to true.
- Otherwise, generate 1-3 follow-up queries (< 50 chars each, same language \
as topic) targeting the gaps.  For each, suggest which information domain \
is best.

Iteration: {iteration} of {max_loops}

Summaries:
{summaries}

Respond as JSON:
{{"is_sufficient": true/false,
  "knowledge_gap": "...",
  "follow_up_queries": [
    {{"query": "...", "domain_hint": "auto"}}
  ]}}"""

_SYNTHESIZE = """\
Generate a comprehensive, well-structured answer based on the research \
summaries below.  Include citations from the source references.

Current date: {current_date}
Topic: {topic}

Summaries:
{summaries}

Provide a thorough answer with clear structure and citations."""


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _extract_topic(state: dict[str, Any]) -> str:
    if state.get("research_topic"):
        return state["research_topic"]
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            return msg.content if hasattr(msg, "content") else str(msg)
    if messages:
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)
    return ""


def _now_str() -> str:
    return datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_research_engine(
    model: BaseChatModel,
    sources: list[InformationSource],
    config: ResearchConfig | None = None,
    *,
    _domain: str = "auto",
) -> Any:
    """Build and compile the tool-agnostic research LangGraph.

    Args:
        model: LLM for analysis, reflection, and synthesis.
        sources: Available information sources.
        config: Engine configuration (max loops, parallelism, profiles).
        _domain: Default source domain hint (reserved for future use).

    Returns:
        Compiled LangGraph runnable.
    """
    from .protocol import ResearchConfig
    from .router import SourceRouter

    _default_config = config or ResearchConfig()
    router = SourceRouter(sources, _default_config)
    available_domains = ", ".join(router.available_source_types())

    def analyze_topic_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        # Emit dispatch event (RFC-0020)
        _emit_progress(ResearchDispatchedEvent(topic=topic[:200]).to_dict())
        _emit_progress(ResearchAnalyzeEvent(topic=topic[:200]).to_dict())

        prompt = _ANALYZE_TOPIC.format(
            domains=available_domains,
            current_date=_now_str(),
            topic=topic,
        )

        # Emit internal event to signal we're doing internal LLM work
        _emit_progress(ResearchInternalLLMResponseEvent(response_type="analysis").to_dict())

        resp = model.invoke([{"role": "user", "content": prompt}])
        content = str(resp.content)

        try:
            parsed = json.loads(content)
            sub_questions = parsed.get("sub_questions", [])
        except json.JSONDecodeError:
            sub_questions = [{"question": topic, "suggested_domain": "auto"}]

        _emit_progress(
            ResearchSubQuestionsEvent(
                count=len(sub_questions),
                sub_questions=sub_questions,
            ).to_dict()
        )
        return {
            "_sub_questions": sub_questions,
            "search_summaries": [],
            "sources_gathered": [],
            "loop_count": 0,
        }

    def generate_queries_node(state: dict[str, Any]) -> dict[str, Any]:
        sub_questions = state.get("_sub_questions", [])
        sq_text = "\n".join(
            f"- {sq.get('question', sq)}" if isinstance(sq, dict) else f"- {sq}"
            for sq in sub_questions
        )

        prompt = _GENERATE_QUERIES.format(
            current_date=_now_str(),
            sub_questions=sq_text,
        )

        # Emit internal event to signal we're doing internal LLM work
        _emit_progress(ResearchInternalLLMResponseEvent(response_type="queries").to_dict())

        resp = model.invoke([{"role": "user", "content": prompt}])
        content = str(resp.content)

        try:
            parsed = json.loads(content)
            queries = parsed.get("queries", [])
        except json.JSONDecodeError:
            queries = [{"query": _extract_topic(state), "domain_hint": "auto"}]

        _emit_progress(
            ResearchQueriesGeneratedEvent(
                queries=[q.get("query", q) if isinstance(q, dict) else q for q in queries],
            ).to_dict()
        )
        return {"_queries": queries}

    def route_to_gather(state: dict[str, Any]) -> list[Send]:
        queries = state.get("_queries", [])
        sends = []
        for q in queries:
            query_str = q.get("query", q) if isinstance(q, dict) else str(q)
            domain_hint = (
                q.get("domain_hint", state.get("domain", "auto")) if isinstance(q, dict) else "auto"
            )
            sends.append(
                Send(
                    "gather",
                    {
                        "_gather_query": query_str,
                        "_gather_domain": domain_hint,
                        **{k: v for k, v in state.items() if not k.startswith("_")},
                    },
                )
            )
        return sends

    def gather_node(state: dict[str, Any]) -> dict[str, Any]:
        query = state.get("_gather_query", "")
        domain_hint = state.get("_gather_domain", "auto")

        _emit_progress(
            ResearchGatherEvent(
                query=query,
                domain=domain_hint,
            ).to_dict()
        )

        selected = router.select(query, domain=domain_hint)
        if not selected:
            return {
                "search_summaries": [f"No sources available for: {query}"],
                "sources_gathered": [f"none:{query}"],
            }

        from .protocol import GatherContext

        context = GatherContext(
            topic=_extract_topic(state),
            existing_summaries=state.get("search_summaries", []),
            iteration=state.get("loop_count", 0),
        )

        all_results = []
        for src in selected:
            try:
                # Python 3.10+ compatible event loop handling
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # No event loop in this thread, create one
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                if loop.is_running():
                    # If loop is running, we need to run in a separate thread
                    # Use shared module-level pool to avoid creating temporary pools
                    results = (
                        _get_shared_pool().submit(asyncio.run, src.query(query, context)).result()
                    )
                else:
                    # Loop exists but not running, use it
                    results = loop.run_until_complete(src.query(query, context))
                all_results.extend(results)
            except Exception:
                logger.debug("Source %s failed for query: %s", src.name, query, exc_info=True)

        if not all_results:
            return {
                "search_summaries": [f"No results from sources for: {query}"],
                "sources_gathered": [f"empty:{query}"],
            }

        summary_parts = []
        source_refs = []
        for r in all_results:
            summary_parts.append(f"[{r.source_name}] {r.content}")
            source_refs.append(f"{r.source_name}:{r.source_ref}")

        _emit_progress(
            ResearchGatherDoneEvent(
                query=query,
                result_count=len(all_results),
                sources_used=list({r.source_name for r in all_results}),
            ).to_dict()
        )

        return {
            "search_summaries": ["\n".join(summary_parts)],
            "sources_gathered": source_refs,
        }

    def summarize_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        summaries = state.get("search_summaries", [])

        if len(summaries) <= 1:
            return {}

        half = len(summaries) // 2
        existing = "\n\n".join(summaries[:half]) if half > 0 else "(none yet)"
        new_results = "\n\n".join(summaries[half:])

        prompt = _SUMMARIZE.format(
            topic=topic,
            existing_summaries=existing[:3000],
            new_results=new_results[:3000],
        )
        resp = model.invoke([{"role": "user", "content": prompt}])
        integrated = str(resp.content)

        _emit_progress(
            ResearchSummarizeEvent(
                total_summaries=len(summaries),
            ).to_dict()
        )

        return {"search_summaries": [integrated]}

    def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        loop_count = state.get("loop_count", 0)
        summaries = "\n\n".join(state.get("search_summaries", []))

        _emit_progress(
            ResearchReflectEvent(
                loop=loop_count + 1,
            ).to_dict()
        )

        prompt = _REFLECT.format(
            topic=topic,
            iteration=loop_count + 1,
            max_loops=state.get("max_loops", _default_config.max_loops),
            summaries=summaries[:4000] or "(no summaries yet)",
        )

        # Emit internal event to signal we're doing internal LLM work
        _emit_progress(ResearchInternalLLMResponseEvent(response_type="reflection").to_dict())

        resp = model.invoke([{"role": "user", "content": prompt}])
        content = str(resp.content)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"is_sufficient": True, "knowledge_gap": "", "follow_up_queries": []}

        is_sufficient = parsed.get("is_sufficient", True)
        follow_ups = parsed.get("follow_up_queries", [])
        knowledge_gap = parsed.get("knowledge_gap", "")

        _emit_progress(
            ResearchReflectionDoneEvent(
                loop=loop_count + 1,
                is_sufficient=is_sufficient,
                follow_up_count=len(follow_ups),
            ).to_dict()
        )

        # IG-089: Emit judgement event with meaningful summary (visible at normal verbosity)
        if is_sufficient:
            judgement_text = "Research complete"
            action_text = "complete"
        else:
            gap_desc = knowledge_gap[:50] if knowledge_gap else "more sources needed"
            judgement_text = f"Need {gap_desc}"
            action_text = "continue"
        _emit_progress(
            ResearchJudgementEvent(
                judgement=judgement_text,
                action=action_text,
            ).to_dict()
        )

        return {
            "loop_count": loop_count + 1,
            "_is_sufficient": is_sufficient,
            "_follow_up_queries": follow_ups,
        }

    def route_after_reflection(state: dict[str, Any]) -> list[Send] | str:
        max_loops = state.get("max_loops", _default_config.max_loops)
        if state.get("_is_sufficient") or state.get("loop_count", 0) >= max_loops:
            return "synthesize"

        follow_ups = state.get("_follow_up_queries", [])
        if follow_ups:
            sends = []
            for fq in follow_ups:
                query_str = fq.get("query", fq) if isinstance(fq, dict) else str(fq)
                domain_hint = fq.get("domain_hint", "auto") if isinstance(fq, dict) else "auto"
                sends.append(
                    Send(
                        "gather",
                        {
                            "_gather_query": query_str,
                            "_gather_domain": domain_hint,
                            **{k: v for k, v in state.items() if not k.startswith("_")},
                        },
                    )
                )
            return sends

        return "synthesize"

    def synthesize_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        summaries = "\n\n".join(state.get("search_summaries", []))
        num_sources = len(state.get("sources_gathered", []))

        _emit_progress(
            ResearchSynthesizeEvent(
                topic=topic[:200],
                total_sources=num_sources,
            ).to_dict()
        )

        prompt = _SYNTHESIZE.format(
            current_date=_now_str(),
            topic=topic,
            summaries=summaries[:6000],
        )
        resp = model.invoke([{"role": "user", "content": prompt}])
        answer = str(resp.content)

        _emit_progress(
            ResearchCompletedEvent(
                answer_length=len(answer),
            ).to_dict()
        )
        return {"answer": answer}

    graph = StateGraph(ResearchEngineState)

    graph.add_node("analyze_topic", analyze_topic_node)
    graph.add_node("generate_queries", generate_queries_node)
    graph.add_node("gather", gather_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "analyze_topic")
    graph.add_edge("analyze_topic", "generate_queries")
    graph.add_conditional_edges("generate_queries", route_to_gather, ["gather"])
    graph.add_edge("gather", "summarize")
    graph.add_edge("summarize", "reflect")
    graph.add_conditional_edges("reflect", route_after_reflection, ["gather", "synthesize"])
    graph.add_edge("synthesize", END)

    return graph.compile()
