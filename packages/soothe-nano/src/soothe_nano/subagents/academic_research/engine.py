"""academic_research engine — iterative academic literature research loop."""

from __future__ import annotations

import asyncio
import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from soothe_nano.subagents._research_timeouts import effective_source_timeout_sec
from soothe_nano.subagents._research_topic_util import (
    planned_research_topic,
    topic_without_attachments,
)
from soothe_nano.subagents.research_wire import ResearchWireEmitter
from soothe_nano.toolkits.url_crawl import crawl_urls, urls_from_search_results
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event

from .display_summary import academic_research_brief_summary_for_display
from .effort import resolve_effort
from .events import (
    AcademicResearchCompletedEvent,
    AcademicResearchCrawlSummaryEvent,
    AcademicResearchGatherSummaryEvent,
    AcademicResearchProgressEvent,
    AcademicResearchStartedEvent,
    AcademicResearchStepCompletedEvent,
)
from .json_util import (
    compact_search_query,
    fallback_queries,
    fallback_sub_questions,
    llm_response_text,
    parse_json_object,
)
from .persistence import format_saved_report_answer, save_academic_research_report
from .protocol import (
    SCOPE_BANNER,
    AcademicResearchConfig,
    GatherContext,
    ResearchReference,
    SourceResult,
)
from .references import (
    format_references_section,
    merge_references,
    reference_from_source_result,
)
from .report_classifier import classify_report_scenario
from .termination import LoopTerminationChecker

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from .effort import AcademicResearchEffortProfile
    from .protocol import AcademicSearchSourceProtocol

logger = logging.getLogger(__name__)

_research_wire = ResearchWireEmitter(
    progress_event_type=AcademicResearchProgressEvent,
    step_event_type=AcademicResearchStepCompletedEvent,
    logger=logger,
)

_shared_pool: ThreadPoolExecutor | None = None


def _get_shared_pool() -> ThreadPoolExecutor:
    global _shared_pool
    if _shared_pool is None:
        _shared_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="academic-research")
        atexit.register(_cleanup_pool)
    return _shared_pool


def _cleanup_pool() -> None:
    global _shared_pool
    if _shared_pool is not None:
        _shared_pool.shutdown(wait=True)
        _shared_pool = None


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
        return _get_shared_pool().submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


class AcademicResearchEngineState(dict):
    messages: Annotated[list, add_messages]
    research_topic: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    references_gathered: Annotated[list, add]
    effort: str
    max_loops: int
    loop_count: int
    _sub_questions: list
    _queries: list
    _is_sufficient: bool
    _follow_up_queries: list
    answer: str


_PLAN_RESEARCH = """\
You are an academic literature analyst. For the material below:
1. Extract research_topic: a concise research goal (1-3 sentences). Use the
   user ask and any attached materials to refine scope. Do NOT copy attached
   file bodies, long quotes, or host context/UI blocks into research_topic.
2. Identify key research sub-questions.
3. Generate targeted academic search queries (< 50 chars, same language as the user ask).

Current date: {current_date}
Material: {topic}
{effort_hint}

Return ONLY raw JSON:
{{"research_topic": "...",
  "sub_questions": [{{"question": "..."}}],
  "queries": [{{"query": "..."}}]}}"""

_SUMMARIZE = """\
Summarise raw academic search results for "{topic}". Preserve source references.
Existing: {existing_summaries}
New: {new_results}
Provide a concise integrated summary."""

_REFLECT = """\
Evaluate web research summaries for "{topic}".
- If sufficient for a thorough public-web report, set is_sufficient true.
- Otherwise provide follow-up search queries (< 50 chars).

{effort_hint}

Summaries:
{summaries}

Return ONLY raw JSON:
{{"is_sufficient": true/false,
  "follow_up_queries": [{{"query": "..."}}]}}"""

_SYNTHESIZE = """\
Write a structured research report for: {topic}

Current date: {current_date}

MANDATORY: Begin with a "## Scope" section containing exactly:
{scope_banner}

Report scenario: {scenario}
Sections (use these headings): {sections}
Contextual focus: {contextual_focus}
Evidence emphasis: {evidence_emphasis}

Use GFM tables and bullet lists where helpful. Write for the reader who asked.

Evidence gathered:
{summaries}
"""


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
    from soothe_nano.utils.prompt_clock import local_date_str

    return local_date_str()


def _effort_profile(
    state: dict[str, Any], config: AcademicResearchConfig
) -> AcademicResearchEffortProfile:
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
    refs: list[ResearchReference] = []
    for item in state.get("references_gathered", []):
        if isinstance(item, ResearchReference):
            refs.append(item)
        elif isinstance(item, dict):
            refs.append(ResearchReference.model_validate(item))
    return refs


def _emit_progress(phase: str, message: str, *, loop_count: int = 0, total_loops: int = 0) -> None:
    _research_wire.progress(phase, message, loop_count=loop_count, total_loops=total_loops)


def _emit_step(tool_name: str, args_preview: str, *, duration_ms: int = 0) -> None:
    _research_wire.step(tool_name, args_preview, duration_ms=duration_ms)


async def _invoke_llm_with_timeout(
    model: Any,
    messages: list[dict[str, str]],
    timeout_sec: float,
    *,
    soothe_config: Any | None = None,
) -> Any:
    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )

    llm_config = llm_rate_limit_config_from(soothe_config).model_copy(
        update={
            "call_timeout_seconds": int(timeout_sec),
            "call_timeout_max_seconds": int(timeout_sec),
        }
    )

    async def _call() -> Any:
        return await model.ainvoke(messages)

    return await await_with_llm_call_policy(_call, config=llm_config)


def _invoke_llm_sync(
    model: Any,
    messages: list[dict[str, str]],
    timeout_sec: float,
    *,
    soothe_config: Any | None = None,
) -> Any:
    return _run_async(
        _invoke_llm_with_timeout(model, messages, timeout_sec, soothe_config=soothe_config)
    )


def build_academic_research_engine(
    model: BaseChatModel,
    academic_source: AcademicSearchSourceProtocol,
    config: AcademicResearchConfig | None = None,
    *,
    synthesis_model: BaseChatModel | None = None,
    soothe_config: Any | None = None,
) -> Any:
    """Build and compile the academic_research LangGraph."""
    cfg = config or AcademicResearchConfig()
    loop_model = model
    final_model = synthesis_model or model

    def plan_research_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        effort, profile = resolve_effort(
            cfg,
            topic=topic,
            context_effort=state.get("effort"),
            context_max_loops=state.get("max_loops")
            if isinstance(state.get("max_loops"), int)
            else None,
        )
        emit_subagent_wire_event(
            AcademicResearchStartedEvent(topic_preview=str(topic)[:200], effort=effort).to_dict(),
            logger,
        )
        _emit_progress("plan", f"Planning research: {topic[:60]}...", total_loops=profile.max_loops)
        prompt = _PLAN_RESEARCH.format(
            current_date=_now_str(),
            topic=topic,
            effort_hint=profile.plan_hint,
        )
        try:
            resp = _invoke_llm_sync(
                loop_model,
                [{"role": "user", "content": prompt}],
                cfg.llm_timeout_sec,
                soothe_config=soothe_config,
            )
            parsed = parse_json_object(llm_response_text(resp))
        except Exception:
            logger.warning("[academic_research] plan timed out, using fallback", exc_info=True)
            parsed = None
        planned_topic = planned_research_topic(parsed, topic)
        sub_questions = (parsed or {}).get("sub_questions") or fallback_sub_questions(planned_topic)
        queries = (parsed or {}).get("queries") or fallback_queries(planned_topic, sub_questions)
        sub_questions = _cap_list(sub_questions, profile.max_sub_questions)
        queries = _cap_list(queries, profile.max_initial_queries)
        _emit_step("PlanResearch", f"{len(queries)} queries")
        # LLM-extracted topic (fallback: strip attachments). Attachment bodies
        # stay out of gather/reflect/synthesize.
        return {
            "_sub_questions": sub_questions,
            "_queries": queries,
            "research_topic": planned_topic,
            "search_summaries": [],
            "sources_gathered": [],
            "references_gathered": [],
            "effort": effort,
            "max_loops": profile.max_loops,
            "loop_count": 0,
        }

    def route_to_gather(state: dict[str, Any]) -> list[Send]:
        profile = _effort_profile(state, cfg)
        queries = _cap_list(state.get("_queries", []), profile.max_initial_queries)
        if not queries:
            topic = _extract_topic(state)
            queries = fallback_queries(topic, state.get("_sub_questions"))
        return [
            Send(
                "gather",
                {
                    "_gather_query": compact_search_query(
                        q.get("query", q) if isinstance(q, dict) else str(q), max_len=120
                    ),
                    **{k: v for k, v in state.items() if not k.startswith("_")},
                },
            )
            for q in queries
        ]

    def gather_node(state: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        query = state.get("_gather_query", "")
        profile = _effort_profile(state, cfg)
        loop_count = state.get("loop_count", 0)
        _emit_progress(
            "gather",
            f"Searching academic sources: {query[:50]}...",
            loop_count=loop_count,
            total_loops=profile.max_loops,
        )
        context = GatherContext(
            topic=_extract_topic(state),
            existing_summaries=state.get("search_summaries", []),
            iteration=loop_count,
        )

        async def _search() -> list[SourceResult]:
            try:
                return await asyncio.wait_for(
                    academic_source.query(query, context),
                    timeout=effective_source_timeout_sec(cfg.source_timeout_sec, soothe_config),
                )
            except Exception:
                logger.debug("[academic_research] academic search failed", exc_info=True)
                return []

        search_results = _run_async(_search())
        sources_touched = len({r.source_ref for r in search_results if r.source_ref})
        emit_subagent_wire_event(
            AcademicResearchGatherSummaryEvent(
                query_preview=str(query)[:120],
                result_count=len(search_results),
                sources_touched=sources_touched,
            ).to_dict(),
            logger,
        )
        if not search_results:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            _emit_step("AcademicSearch", f"{query[:80]} → 0 hits", duration_ms=duration_ms)
            return {
                "search_summaries": [f"No academic results for: {query}"],
                "sources_gathered": [f"empty:{query}"],
            }

        urls = urls_from_search_results(search_results, limit=profile.crawl_top_n)

        async def _crawl() -> list[Any]:
            return await crawl_urls(
                urls,
                config=cfg,
                timeout_sec=cfg.crawl_timeout_sec,
            )

        crawl_results = _run_async(_crawl()) if urls else []
        success_count = sum(1 for c in crawl_results if c.success)
        emit_subagent_wire_event(
            AcademicResearchCrawlSummaryEvent(
                urls_crawled=len(urls), success_count=success_count
            ).to_dict(),
            logger,
        )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        preview = f"{query[:80]} → {len(search_results)} hits"
        if urls:
            preview = f"{preview}, {success_count}/{len(urls)} crawled"
        _emit_step("AcademicSearch", preview, duration_ms=duration_ms)

        summary_parts: list[str] = []
        source_refs: list[str] = []
        ref_dicts: list[dict] = []
        for r in search_results:
            summary_parts.append(f"[academic] {r.content[:2000]}")
            source_refs.append(f"academic_search:{r.source_ref}")
            ref_dicts.append(reference_from_source_result(r, query=query).model_dump(mode="json"))
        for crawled in crawl_results:
            if not crawled.success or not crawled.content:
                continue
            summary_parts.append(f"[crawl:{crawled.url}] {crawled.content[:3000]}")
            crawl_result = SourceResult(
                content=crawled.content,
                source_ref=crawled.url,
                source_name="url_crawl",
                metadata={"url": crawled.url, "title": crawled.title},
            )
            source_refs.append(f"url_crawl:{crawled.url}")
            ref_dicts.append(
                reference_from_source_result(crawl_result, query=query).model_dump(mode="json")
            )

        return {
            "search_summaries": ["\n".join(summary_parts)],
            "sources_gathered": source_refs,
            "references_gathered": ref_dicts,
        }

    def summarize_node(state: dict[str, Any]) -> dict[str, Any]:
        summaries = state.get("search_summaries", [])
        if len(summaries) <= 1:
            return {}
        combined = sum(len(s) for s in summaries)
        if combined <= 3000:
            return {}
        topic = _extract_topic(state)
        half = len(summaries) // 2
        prompt = _SUMMARIZE.format(
            topic=topic,
            existing_summaries="\n\n".join(summaries[:half])[:3000],
            new_results="\n\n".join(summaries[half:])[:3000],
        )
        try:
            resp = _invoke_llm_sync(
                loop_model,
                [{"role": "user", "content": prompt}],
                cfg.summarize_timeout_sec,
                soothe_config=soothe_config,
            )
            return {"search_summaries": [str(resp.content)]}
        except Exception:
            return {}

    def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
        topic = _extract_topic(state)
        profile = _effort_profile(state, cfg)
        loop_count = state.get("loop_count", 0)
        if cfg.enable_early_termination and loop_count >= 1:
            refs = _references_from_state(state)
            current = [
                SourceResult(
                    content=r.query or "", source_ref=r.source_ref, source_name=r.source_name
                )
                for r in refs[-10:]
            ]
            decision = LoopTerminationChecker(
                min_results=cfg.min_results_for_termination,
                min_source_diversity=cfg.min_source_diversity,
            ).check_termination(state, loop_count, current)
            if decision.should_terminate:
                return {
                    "loop_count": loop_count + 1,
                    "_is_sufficient": True,
                    "_follow_up_queries": [],
                }
        summaries = "\n\n".join(state.get("search_summaries", []))
        prompt = _REFLECT.format(
            topic=topic,
            summaries=summaries[:4000] or "(none)",
            effort_hint=profile.reflect_follow_up_hint,
        )
        try:
            resp = _invoke_llm_sync(
                loop_model,
                [{"role": "user", "content": prompt}],
                cfg.llm_timeout_sec,
                soothe_config=soothe_config,
            )
            parsed = parse_json_object(llm_response_text(resp)) or {
                "is_sufficient": True,
                "follow_up_queries": [],
            }
        except Exception:
            parsed = {"is_sufficient": True, "follow_up_queries": []}
        _emit_step("Reflect", "sufficient" if parsed.get("is_sufficient") else "follow-ups")
        return {
            "loop_count": loop_count + 1,
            "_is_sufficient": parsed.get("is_sufficient", True),
            "_follow_up_queries": parsed.get("follow_up_queries", []),
        }

    def route_after_reflection(state: dict[str, Any]) -> list[Send] | str:
        profile = _effort_profile(state, cfg)
        if state.get("_is_sufficient") or state.get("loop_count", 0) >= state.get(
            "max_loops", profile.max_loops
        ):
            return "synthesize"
        follow_ups = _cap_list(state.get("_follow_up_queries", []), profile.max_follow_up_queries)
        if follow_ups:
            return [
                Send(
                    "gather",
                    {
                        "_gather_query": compact_search_query(
                            fq.get("query", fq) if isinstance(fq, dict) else str(fq), max_len=120
                        ),
                        **{k: v for k, v in state.items() if not k.startswith("_")},
                    },
                )
                for fq in follow_ups
            ]
        return "synthesize"

    def synthesize_node(state: dict[str, Any]) -> dict[str, Any]:
        # Never feed attached file bodies into synthesis — only gathered evidence.
        topic = topic_without_attachments(_extract_topic(state))
        summaries = "\n\n".join(state.get("search_summaries", []))
        effort = state.get("effort", "normal")
        num_sources = len(state.get("sources_gathered", []))
        t0 = time.perf_counter()

        async def _classify() -> Any:
            return await classify_report_scenario(
                loop_model,
                topic=topic,
                effort=str(effort),
                loop_count=state.get("loop_count", 0),
                source_count=num_sources,
                soothe_config=soothe_config,
                timeout_sec=cfg.llm_timeout_sec,
            )

        classification = _run_async(_classify())
        prompt = _SYNTHESIZE.format(
            current_date=_now_str(),
            topic=topic,
            scope_banner=SCOPE_BANNER,
            scenario=classification.scenario,
            sections=", ".join(classification.sections),
            contextual_focus="; ".join(classification.contextual_focus) or topic[:200],
            evidence_emphasis=classification.evidence_emphasis,
            summaries=summaries[:8000],
        )
        try:
            resp = _invoke_llm_sync(
                final_model,
                [{"role": "user", "content": prompt}],
                cfg.synthesize_timeout_sec,
                soothe_config=soothe_config,
            )
            report = str(resp.content)
        except Exception:
            report = f"## Scope\n\n{SCOPE_BANNER}\n\n## Key Findings\n\n{summaries[:6000]}"
        if SCOPE_BANNER not in report:
            report = f"## Scope\n\n{SCOPE_BANNER}\n\n{report}"
        refs = merge_references(_references_from_state(state))
        bib = format_references_section(refs, accessed_date=_now_str())
        if bib and bib not in report:
            report = f"{report.rstrip()}\n\n{bib}"
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        saved = (
            save_academic_research_report(
                report,
                topic=topic,
                soothe_config=soothe_config,
            )
            if cfg.save_reports
            else None
        )
        summary = (
            saved.brief_summary
            if saved is not None
            else academic_research_brief_summary_for_display(report)
        )
        report_path = saved.display_path if saved is not None else ""
        _emit_step("Synthesize", classification.scenario, duration_ms=elapsed_ms)
        emit_subagent_wire_event(
            AcademicResearchCompletedEvent(
                duration_ms=elapsed_ms,
                scenario=classification.scenario,
                report_length=len(report),
                summary=summary,
                report_path=report_path,
            ).to_dict(),
            logger,
        )
        answer = format_saved_report_answer(saved) if saved is not None else report
        return {"answer": answer, "messages": [AIMessage(content=answer)]}

    graph = StateGraph(AcademicResearchEngineState)
    graph.add_node("plan_research", plan_research_node)
    graph.add_node("gather", gather_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_edge(START, "plan_research")
    graph.add_conditional_edges("plan_research", route_to_gather, ["gather"])
    graph.add_edge("gather", "summarize")
    graph.add_edge("summarize", "reflect")
    graph.add_conditional_edges("reflect", route_after_reflection, ["gather", "synthesize"])
    graph.add_edge("synthesize", END)
    return graph.compile()
