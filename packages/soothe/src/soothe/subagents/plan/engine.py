"""Plan subagent LangGraph (RFC-618).

Agentic information collection (multiple explore invokes per round, multiple rounds)
followed by agentic plan design loops, then a single delegate final message.
"""

from __future__ import annotations

import logging
import operator
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.utils.llm.structured import invoke_structured_chat_typed

from .schemas import CollectorDecision, PlanRefinement, PlanSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)


class PlanEngineState(dict):
    """Graph state: ``messages`` satisfies CompiledSubAgent contract."""

    messages: Annotated[list[Any], add_messages]
    task_text: str
    findings: Annotated[list[str], operator.add]
    collection_round: int
    plan_markdown: str
    plan_round: int
    finish_collection: bool
    finish_planning: bool
    explores_used: int


_COLLECTOR_SYSTEM = """You are the **collection** phase of Soothe's plan subagent. The parent \
agent delegated a task. Your job is to decide what **readonly workspace recon** is still needed \
before a solid execution plan can be written.

You may request **multiple independent explore passes** in one round by listing several \
`explore_tasks` (each becomes one explore sub-invocation). Keep directives precise: paths, \
symbols, filenames, or concrete questions about the repo.

Rules:
- Only readonly workspace search (explore). No shell mutation, no edits, no web unless the \
parent task explicitly requires external facts (then set finish_collection and say so in rationale).
- Prefer **disjoint** scopes per task when searching a large tree.
- Set `finish_collection` true when gathered evidence is enough for downstream planning, or when \
further explore would not change the plan meaningfully.
- You see prior rounds' findings in the user message; do not repeat the same explore verbatim \
unless prior output was empty or clearly wrong."""


_PLANNER_SYSTEM = """You are the **plan design** phase of Soothe's plan subagent. You already have \
(optional) readonly workspace findings from explore. Produce an **execution-oriented markdown plan** \
for the parent orchestrator: objective, ordered steps, dependencies, risks, and open questions.

Rules:
- Output the **full** plan in `plan_markdown` each round (not a diff), refined as you learn.
- Set `finish_planning` true when the plan is actionable and stable enough to hand back.
- Do not claim non-readonly work was done; explore was readonly only.
- If findings are thin, still produce the best plan you can and list assumptions explicitly."""


def _format_findings(state: dict[str, Any]) -> str:
    parts = state.get("findings") or []
    if not parts:
        return "(no workspace findings yet)"
    return "\n\n---\n\n".join(parts)[:24000]


def build_plan_engine(
    model: BaseChatModel,
    explore_runnable: Runnable,
    plan_config: PlanSubagentConfig,
) -> Any:
    """Compile the plan subagent graph."""

    def ingest_task(state: dict[str, Any]) -> dict[str, Any]:
        text = ""
        for msg in reversed(state.get("messages") or []):
            if getattr(msg, "type", None) == "human":
                content = getattr(msg, "content", "")
                text = content if isinstance(content, str) else str(content)
                break
        if not text and state.get("messages"):
            last = state["messages"][-1]
            c = getattr(last, "content", "")
            text = c if isinstance(c, str) else str(c)
        logger.info("Plan subagent: ingested task (%d chars)", len(text))
        return {
            "task_text": text,
            "collection_round": 0,
            "plan_markdown": "",
            "plan_round": 0,
            "finish_collection": False,
            "finish_planning": False,
            "explores_used": 0,
        }

    async def collection_iteration(state: dict[str, Any]) -> dict[str, Any]:
        from langgraph.config import get_config

        task = state.get("task_text", "")
        rnd = int(state.get("collection_round", 0)) + 1
        findings_block = _format_findings(state)
        user = (
            f"## Delegated task\n{task}\n\n## Collection round\n{rnd} / {plan_config.max_collection_rounds}\n\n"
            f"## Findings so far\n{findings_block}"
        )
        try:
            decision = await invoke_structured_chat_typed(
                model,
                [
                    {"role": "system", "content": _COLLECTOR_SYSTEM},
                    {"role": "user", "content": user},
                ],
                CollectorDecision,
            )
        except Exception:
            logger.exception("Plan subagent: collector structured output failed")
            decision = CollectorDecision(
                explore_tasks=[],
                rationale="collector_failed",
                finish_collection=True,
            )

        new_findings: list[str] = []
        explores_used = int(state.get("explores_used", 0))
        cfg = get_config()

        if plan_config.enable_explore:
            tasks = list(decision.explore_tasks)[: plan_config.max_explore_tasks_per_round]
            for i, focus in enumerate(tasks):
                if explores_used >= plan_config.max_explore_passes:
                    logger.info(
                        "Plan subagent: explore cap hit (%d); stopping batch",
                        plan_config.max_explore_passes,
                    )
                    break
                focus = (focus or "").strip()
                if not focus:
                    continue
                label = f"R{rnd}-E{i + 1}"
                try:
                    out = await explore_runnable.ainvoke(
                        {"messages": [HumanMessage(content=focus)]}, cfg
                    )
                except Exception:
                    logger.exception("Plan subagent: explore failed for %s", label)
                    new_findings.append(f"### {label}\n_(explore invoke failed — see logs)_\n")
                    explores_used += 1
                    continue
                msgs = out.get("messages") if isinstance(out, dict) else None
                body = ""
                if msgs:
                    last = msgs[-1]
                    body = getattr(last, "content", "") or ""
                    if not isinstance(body, str):
                        body = str(body)
                new_findings.append(f"### {label}: {focus[:120]}\n{body.strip()}\n")
                explores_used += 1
                logger.info("Plan subagent: explore %s (%d total)", label, explores_used)

        finish = bool(decision.finish_collection)
        if rnd >= plan_config.max_collection_rounds:
            finish = True

        return {
            "collection_round": rnd,
            "findings": new_findings,
            "finish_collection": finish,
            "explores_used": explores_used,
        }

    async def plan_iteration(state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task_text", "")
        pr = int(state.get("plan_round", 0)) + 1
        prev = (state.get("plan_markdown") or "").strip()
        findings_block = _format_findings(state)
        user = (
            f"## Delegated task\n{task}\n\n## Plan design round\n{pr} / {plan_config.max_plan_rounds}\n\n"
            f"## Workspace findings\n{findings_block}\n\n"
            f"## Previous plan draft\n{prev or '(none — write initial plan)'}"
        )
        try:
            ref = await invoke_structured_chat_typed(
                model,
                [
                    {"role": "system", "content": _PLANNER_SYSTEM},
                    {"role": "user", "content": user},
                ],
                PlanRefinement,
            )
        except Exception:
            logger.exception("Plan subagent: planner structured output failed")
            ref = PlanRefinement(
                plan_markdown=f"## Plan\n\n1. Address: {task}\n",
                rationale="planner_failed_fallback",
                finish_planning=True,
            )

        done = bool(ref.finish_planning) or pr >= plan_config.max_plan_rounds
        logger.info(
            "Plan subagent: plan round %d complete (finish=%s, md_len=%d)",
            pr,
            done,
            len(ref.plan_markdown or ""),
        )
        return {
            "plan_round": pr,
            "plan_markdown": (ref.plan_markdown or "").strip(),
            "finish_planning": done,
        }

    def emit_final(state: dict[str, Any]) -> dict[str, Any]:
        body = (state.get("plan_markdown") or "").strip() or "(no plan produced)"
        return {"messages": [AIMessage(content=body)]}

    def route_after_ingest(_state: dict[str, Any]) -> str:
        if plan_config.enable_explore:
            return "collect"
        return "plan"

    def route_after_collection(state: dict[str, Any]) -> str:
        if state.get("finish_collection"):
            return "plan"
        if int(state.get("collection_round", 0)) >= plan_config.max_collection_rounds:
            return "plan"
        return "collect"

    def route_after_plan(state: dict[str, Any]) -> str:
        if state.get("finish_planning"):
            return "done"
        if int(state.get("plan_round", 0)) >= plan_config.max_plan_rounds:
            return "done"
        return "plan"

    graph = StateGraph(PlanEngineState)
    graph.add_node("ingest_task", ingest_task)
    graph.add_node("collection_iteration", collection_iteration)
    graph.add_node("plan_iteration", plan_iteration)
    graph.add_node("emit_final", emit_final)

    graph.add_edge(START, "ingest_task")
    graph.add_conditional_edges(
        "ingest_task",
        route_after_ingest,
        {"collect": "collection_iteration", "plan": "plan_iteration"},
    )
    graph.add_conditional_edges(
        "collection_iteration",
        route_after_collection,
        {"collect": "collection_iteration", "plan": "plan_iteration"},
    )
    graph.add_conditional_edges(
        "plan_iteration",
        route_after_plan,
        {"plan": "plan_iteration", "done": "emit_final"},
    )
    graph.add_edge("emit_final", END)

    return graph.compile()
