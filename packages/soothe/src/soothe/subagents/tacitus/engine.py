"""Tacitus engine — iterative public-domain research loop.

analyze_topic -> generate_queries -> gather -> summarize -> reflect -> synthesize
"""

from __future__ import annotations

import asyncio
import atexit
import datetime
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from soothe.utils.subagent_emit import emit_subagent_wire_event

from .display_summary import tacitus_answer_summary_for_display
from .effort import resolve_effort
from .events import TacitusCompletedEvent, TacitusGatherSummaryEvent, TacitusStartedEvent
from .json_util import (
    compact_search_query,
    fallback_queries,
    fallback_sub_questions,
    llm_response_text,
    parse_json_object,
)
from .protocol import ResearchReference
from .references import (
    format_references_section,
    merge_references,
    reference_from_source_result,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from .effort import TacitusEffortProfile
    from .protocol import PublicInformationSource, TacitusConfig

logger = logging.getLogger(__name__)

# Module-level shared thread pool for async-to-sync conversion in research engine
# This prevents creating new thread pools for each query
_shared_pool: ThreadPoolExecutor | None = None


def _get_shared_pool() -> ThreadPoolExecutor:
    """Get or create the shared thread pool."""
    global _shared_pool
    if _shared_pool is None:
        _shared_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tacitus-async")
        atexit.register(_cleanup_pool)
    return _shared_pool


def _cleanup_pool() -> None:
    """Cleanup the shared thread pool on exit."""
    global _shared_pool
    if _shared_pool is not None:
        _shared_pool.shutdown(wait=True)
        _shared_pool = None


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class TacitusEngineState(dict):
    """Top-level state for the Tacitus engine graph."""

    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str  # profile hint: public | web | academic
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    references_gathered: Annotated[list, add]
    effort: str
    max_loops: int
    loop_count: int
    # Loop scratch (must be declared or LangGraph drops them between nodes).
    _sub_questions: list
    _queries: list
    _is_sufficient: bool
    _follow_up_queries: list
    answer: str


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_ANALYZE_TOPIC = """\
You are a research analyst. Analyse the following topic and identify the key \
sub-questions that need to be answered.  For each sub-question, indicate \
which information domain is most likely to have the answer.

Profiles available: {domains} (public, web, academic)

Current date: {current_date}

Topic: {topic}

{effort_hint}

Return ONLY a raw JSON object (no markdown fences):
{{"sub_questions": [
    {{"question": "...", "suggested_domain": "public|web|academic"}}
]}}"""

_GENERATE_QUERIES = """\
Generate targeted search queries for the following sub-questions.
Each query should be concise (< 50 characters) and in the same language \
as the original topic.

Current date: {current_date}

Sub-questions:
{sub_questions}

{effort_hint}

Return ONLY a raw JSON object (no markdown fences):
{{"queries": [
    {{"query": "...", "domain_hint": "public|web|academic"}}
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
- Otherwise, generate follow-up queries (< 50 chars each, same language \
as topic) targeting the gaps.  For each, suggest which information domain \
is best.

{effort_hint}

Summaries:
{summaries}

Return ONLY a raw JSON object (no markdown fences):
{{"is_sufficient": true/false,
  "knowledge_gap": "...",
  "follow_up_queries": [
    {{"query": "...", "domain_hint": "public"}}
  ]}}"""

_SYNTHESIZE = """\
Generate a comprehensive, well-structured answer based on the research \
summaries below.  Use inline citations where helpful; a formatted reference \
list is appended automatically after your answer.

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


def _effort_profile_for_state(state: dict[str, Any], config: TacitusConfig) -> TacitusEffortProfile:
    topic = _extract_topic(state)
    ctx_loops = state.get("max_loops")
    context_max_loops = ctx_loops if isinstance(ctx_loops, int) else None
    _, profile = resolve_effort(
        config,
        topic=topic,
        context_effort=state.get("effort"),
        context_max_loops=context_max_loops,
    )
    return profile


def _cap_list(items: list[Any], limit: int) -> list[Any]:
    return items[:limit] if limit > 0 else []


def _references_from_state(state: dict[str, Any]) -> list[ResearchReference]:
    raw = state.get("references_gathered", [])
    refs: list[ResearchReference] = []
    for item in raw:
        if isinstance(item, ResearchReference):
            refs.append(item)
        elif isinstance(item, dict):
            refs.append(ResearchReference.model_validate(item))
    return refs


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_tacitus_engine(
    model: BaseChatModel,
    sources: list[PublicInformationSource],
    config: TacitusConfig | None = None,
    *,
    synthesis_model: BaseChatModel | None = None,
    _domain: str = "public",
) -> Any:
    """Build and compile the Tacitus LangGraph."""
    from .protocol import TacitusConfig
    from .router import PublicSemanticRouter

    _default_config = config or TacitusConfig()
    loop_model = model
    final_model = synthesis_model or model
    router = PublicSemanticRouter(sources, _default_config)
    available_domains = "public, web, academic"

    def analyze_topic_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        effort, profile = resolve_effort(
            _default_config,
            topic=topic,
            context_effort=state.get("effort"),
            context_max_loops=state.get("max_loops")
            if isinstance(state.get("max_loops"), int)
            else None,
        )
        emit_subagent_wire_event(
            TacitusStartedEvent(
                topic_preview=str(topic)[:200],
                effort=effort,
            ).to_dict(),
            logger,
        )
        prompt = _ANALYZE_TOPIC.format(
            domains=available_domains,
            current_date=_now_str(),
            topic=topic,
            effort_hint=profile.analyze_question_hint,
        )

        resp = loop_model.invoke([{"role": "user", "content": prompt}])
        parsed = parse_json_object(llm_response_text(resp))
        domain_hint = state.get("domain", _domain) or "public"
        if parsed:
            sub_questions = parsed.get("sub_questions", [])
        else:
            logger.warning("[Tacitus] analyze parse failed, using fallback")
            sub_questions = []
        if not sub_questions:
            logger.warning("[Tacitus] analyze returned no sub-questions, using fallback")
            sub_questions = fallback_sub_questions(topic, domain=domain_hint)

        sub_questions = _cap_list(sub_questions, profile.max_sub_questions)
        logger.info(
            "[Tacitus] effort=%s, %d sub-questions (cap %d)",
            effort,
            len(sub_questions),
            profile.max_sub_questions,
        )
        return {
            "_sub_questions": sub_questions,
            "search_summaries": [],
            "sources_gathered": [],
            "references_gathered": [],
            "effort": effort,
            "max_loops": profile.max_loops,
            "loop_count": 0,
        }

    def generate_queries_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        profile = _effort_profile_for_state(state, _default_config)
        domain_hint = state.get("domain", _domain) or "public"
        sub_questions = state.get("_sub_questions", [])
        if not sub_questions:
            sub_questions = fallback_sub_questions(topic, domain=domain_hint)
        sq_text = "\n".join(
            f"- {sq.get('question', sq)}" if isinstance(sq, dict) else f"- {sq}"
            for sq in sub_questions
        )

        prompt = _GENERATE_QUERIES.format(
            current_date=_now_str(),
            sub_questions=sq_text,
            effort_hint=profile.generate_queries_hint,
        )

        resp = loop_model.invoke([{"role": "user", "content": prompt}])
        parsed = parse_json_object(llm_response_text(resp))
        if parsed:
            queries = parsed.get("queries", [])
        else:
            logger.warning("[Tacitus] query generation parse failed, using fallback")
            queries = []
        if not queries:
            logger.warning("[Tacitus] query generation returned no queries, using fallback")
            queries = fallback_queries(topic, sub_questions, default_domain=domain_hint)

        queries = _cap_list(queries, profile.max_initial_queries)
        logger.info(
            "[Tacitus] generated %d queries (cap %d)",
            len(queries),
            profile.max_initial_queries,
        )
        return {"_queries": queries}

    def route_to_gather(state: dict[str, Any]) -> list[Send]:
        profile = _effort_profile_for_state(state, _default_config)
        queries = _cap_list(state.get("_queries", []), profile.max_initial_queries)
        if not queries:
            topic = _extract_topic(state)
            domain_hint = state.get("domain", _domain) or "public"
            logger.warning("[Tacitus] no queries to gather, using topic fallback")
            queries = fallback_queries(
                topic,
                state.get("_sub_questions"),
                default_domain=domain_hint,
            )
        sends = []
        for q in queries:
            query_str = compact_search_query(
                q.get("query", q) if isinstance(q, dict) else str(q), max_len=120
            )
            domain_hint = (
                q.get("domain_hint", state.get("domain", "public"))
                if isinstance(q, dict)
                else "public"
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
        domain_hint = state.get("_gather_domain", "public")
        profile = _effort_profile_for_state(state, _default_config)

        selected = router.select(
            query,
            domain=domain_hint,
            max_sources=profile.max_sources_per_query,
        )
        if not selected:
            emit_subagent_wire_event(
                TacitusGatherSummaryEvent(
                    query_preview=str(query)[:120],
                    result_count=0,
                    sources_touched=0,
                ).to_dict(),
                logger,
            )
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
            emit_subagent_wire_event(
                TacitusGatherSummaryEvent(
                    query_preview=str(query)[:120],
                    result_count=0,
                    sources_touched=len(selected),
                ).to_dict(),
                logger,
            )
            return {
                "search_summaries": [f"No results from sources for: {query}"],
                "sources_gathered": [f"empty:{query}"],
            }

        summary_parts = []
        source_refs = []
        ref_dicts: list[dict] = []
        for r in all_results:
            summary_parts.append(f"[{r.source_name}] {r.content}")
            source_refs.append(f"{r.source_name}:{r.source_ref}")
            ref_dicts.append(reference_from_source_result(r, query=query).model_dump(mode="json"))

        emit_subagent_wire_event(
            TacitusGatherSummaryEvent(
                query_preview=str(query)[:120],
                result_count=len(all_results),
                sources_touched=len(source_refs),
            ).to_dict(),
            logger,
        )

        return {
            "search_summaries": ["\n".join(summary_parts)],
            "sources_gathered": source_refs,
            "references_gathered": ref_dicts,
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
        resp = loop_model.invoke([{"role": "user", "content": prompt}])
        integrated = str(resp.content)

        return {"search_summaries": [integrated]}

    def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        profile = _effort_profile_for_state(state, _default_config)
        loop_count = state.get("loop_count", 0)
        summaries = "\n\n".join(state.get("search_summaries", []))

        prompt = _REFLECT.format(
            topic=topic,
            summaries=summaries[:4000] or "(no summaries yet)",
            effort_hint=profile.reflect_follow_up_hint,
        )

        resp = loop_model.invoke([{"role": "user", "content": prompt}])
        parsed = parse_json_object(llm_response_text(resp)) or {
            "is_sufficient": True,
            "knowledge_gap": "",
            "follow_up_queries": [],
        }

        is_sufficient = parsed.get("is_sufficient", True)
        follow_ups = parsed.get("follow_up_queries", [])

        logger.info(
            "[Tacitus] loop %d, sufficient=%s, follow_ups=%d",
            loop_count + 1,
            is_sufficient,
            len(follow_ups),
        )

        return {
            "loop_count": loop_count + 1,
            "_is_sufficient": is_sufficient,
            "_follow_up_queries": follow_ups,
        }

    def route_after_reflection(state: dict[str, Any]) -> list[Send] | str:
        profile = _effort_profile_for_state(state, _default_config)
        max_loops = state.get("max_loops", profile.max_loops)
        if state.get("_is_sufficient") or state.get("loop_count", 0) >= max_loops:
            return "synthesize"

        follow_ups = _cap_list(
            state.get("_follow_up_queries", []),
            profile.max_follow_up_queries,
        )
        if follow_ups:
            sends = []
            for fq in follow_ups:
                query_str = compact_search_query(
                    fq.get("query", fq) if isinstance(fq, dict) else str(fq),
                    max_len=120,
                )
                domain_hint = fq.get("domain_hint", "public") if isinstance(fq, dict) else "public"
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

        prompt = _SYNTHESIZE.format(
            current_date=_now_str(),
            topic=topic,
            summaries=summaries[:6000],
        )
        synth_t0 = time.perf_counter()
        resp = final_model.invoke([{"role": "user", "content": prompt}])
        answer = str(resp.content)
        refs = merge_references(_references_from_state(state))
        if refs:
            bib = format_references_section(refs, accessed_date=_now_str())
            if bib and bib not in answer:
                answer = f"{answer.rstrip()}\n\n{bib}"
        elapsed_ms = int((time.perf_counter() - synth_t0) * 1000)

        logger.info(
            "[Tacitus] synthesized %d chars from %d sources (%d references)",
            len(answer),
            num_sources,
            len(refs),
        )
        completion_summary = tacitus_answer_summary_for_display(answer)
        emit_subagent_wire_event(
            TacitusCompletedEvent(
                duration_ms=elapsed_ms,
                answer_length=len(answer),
                summary=completion_summary,
            ).to_dict(),
            logger,
        )
        return {"answer": answer}

    graph = StateGraph(TacitusEngineState)

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
