"""Plan subagent LangGraph (RFC-618).

Agentic plan design loops, then a single delegate final message.
Readonly workspace recon runs on execute-step threads (file tools), not a separate subagent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe_nano.utils.llm.structured import invoke_structured_chat_typed

from .schemas import PlanRefinement, PlanSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class PlanEngineState(dict):
    """Graph state: ``messages`` satisfies CompiledSubAgent contract."""

    messages: Annotated[list[Any], add_messages]
    task_text: str
    plan_markdown: str
    plan_round: int
    finish_planning: bool


_PLANNER_SYSTEM = """You are the **plan design** phase of Soothe's plan subagent. Produce an \
**execution-oriented markdown plan** for the parent orchestrator: objective, ordered steps, \
dependencies, risks, and open questions.

Rules:
- Output the **full** plan in `plan_markdown` each round (not a diff), refined as you learn.
- Set `finish_planning` true when the plan is actionable and stable enough to hand back.
- Assume readonly repo recon happens on execute-step threads via file tools; do not \
delegate recon-style subagents.
- If context is thin, still produce the best plan you can and list assumptions explicitly."""


def build_plan_engine(
    model: BaseChatModel,
    plan_config: PlanSubagentConfig,
    *,
    soothe_config: Any | None = None,
) -> Any:
    """Compile the plan subagent graph."""
    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )

    llm_policy = llm_rate_limit_config_from(soothe_config)

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
            "plan_markdown": "",
            "plan_round": 0,
            "finish_planning": False,
        }

    async def plan_iteration(state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task_text", "")
        pr = int(state.get("plan_round", 0)) + 1
        prev = (state.get("plan_markdown") or "").strip()
        user = (
            f"## Delegated task\n{task}\n\n## Plan design round\n{pr} / {plan_config.max_plan_rounds}\n\n"
            f"## Previous plan draft\n{prev or '(none — write initial plan)'}"
        )
        try:

            async def _invoke() -> PlanRefinement:
                return await invoke_structured_chat_typed(
                    model,
                    [
                        {"role": "system", "content": _PLANNER_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    PlanRefinement,
                )

            ref = await await_with_llm_call_policy(_invoke, config=llm_policy)
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

    def route_after_plan(state: dict[str, Any]) -> str:
        if state.get("finish_planning"):
            return "done"
        if int(state.get("plan_round", 0)) >= plan_config.max_plan_rounds:
            return "done"
        return "plan"

    graph = StateGraph(PlanEngineState)
    graph.add_node("ingest_task", ingest_task)
    graph.add_node("plan_iteration", plan_iteration)
    graph.add_node("emit_final", emit_final)

    graph.add_edge(START, "ingest_task")
    graph.add_edge("ingest_task", "plan_iteration")
    graph.add_conditional_edges(
        "plan_iteration",
        route_after_plan,
        {"plan": "plan_iteration", "done": "emit_final"},
    )
    graph.add_edge("emit_final", END)

    return graph.compile()
