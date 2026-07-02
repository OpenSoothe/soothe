"""Invoke the compiled Strange Loop graph (RFC-220).

Langfuse (IG-367, IG-396): outer ``ainvoke`` receives the LangChain callback handler so the
Loop Graph run nests planner / CoreAgent spans under one trace; ``langfuse_session_id`` is the
conversation ``thread_id``; Runnable ``configurable.thread_id`` stays ``loop_id`` for checkpoint
routing. Metadata adds ``soothe_component`` and dashboard tags for StrangeLoop.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from soothe.foundation.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.utils.messages import last_ledger_ai_content
from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text
from soothe.utils.observability.langfuse import (
    SootheLangfuse,
    loop_graph_langfuse_run_display_name,
    merge_langfuse_runnable_config,
)

logger = logging.getLogger(__name__)


def _langfuse_goal_output_text(ctx: LoopRuntimeContext) -> str:
    """Best-effort final user-visible text for Langfuse trace output (IG-395)."""
    from soothe.foundation.sloop.engine.continuation_context import ledger_goal_completion_text

    completion = ledger_goal_completion_text(ctx.loop_state.loop_messages)
    if completion:
        return completion
    last = last_ledger_ai_content(ctx.loop_state)
    if last:
        return last
    pp = ctx.loop_state.previous_plan
    if pp is not None:
        if pp.full_output and str(pp.full_output).strip():
            return str(pp.full_output).strip()
        action_text = resolve_plan_action_text(pp)
        if action_text:
            return action_text
    return ""


def build_loop_graph_invoke_config(ctx: LoopRuntimeContext) -> dict[str, Any]:
    """Build RunnableConfig for ``CompiledGraph.ainvoke`` with Langfuse + loop metadata.

    Configurable ``thread_id`` is ``loop_id`` (RFC-220). Langfuse session correlation uses
    ``loop_state.thread_id`` so traces align with planner LLM and CoreAgent execute streams.

    Args:
        ctx: Runtime context for the current goal run.

    Returns:
        RunnableConfig dict safe to pass to ``ainvoke``.
    """
    loop_id = ctx.state_manager.loop_id
    configurable: dict[str, Any] = {"thread_id": loop_id}
    if ctx.loop_state.workspace:
        configurable["workspace"] = ctx.loop_state.workspace
    if ctx.proposal_queue is not None:
        configurable["proposal_queue"] = ctx.proposal_queue

    cfg = ctx.strange_loop.config
    if ctx.goal_trace is not None:
        return ctx.goal_trace.graph_invoke_config(configurable=configurable)

    base = {"configurable": configurable}
    run_name = loop_graph_langfuse_run_display_name(cfg.observability.langfuse.trace_name)
    merged = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id=ctx.loop_state.thread_id,
        run_name=run_name,
        loop_id=loop_id,
    )
    out = dict(merged)
    meta = dict(out.get("metadata") or {})
    meta.setdefault("loop_id", loop_id)
    meta.setdefault("soothe_component", "strange_loop_graph")
    meta.setdefault("soothe_component_version", "strange-loop-v2")
    tags = list(meta.get("langfuse_tags") or [])
    for label in ("goal_execution_loop", "strange-loop-graph"):
        if label not in tags:
            tags.append(label)
    meta["langfuse_tags"] = tags
    out["metadata"] = meta
    return out


async def invoke_strange_loop_graph(ctx: LoopRuntimeContext) -> None:
    """Run the compiled graph once until END.

    Progress is emitted through ``ctx.emit``, which ``StrangeLoop.run_with_progress`` wires
    to an asyncio queue consumer.

    Args:
        ctx: Fully initialized runtime context including ``emit``.
    """
    from langgraph.types import Command

    loop_id = ctx.state_manager.loop_id
    planner = ctx.strange_loop.plan_phase._loop_planner
    if hasattr(planner, "_loop_id"):
        planner._loop_id = loop_id

    compiled = build_strange_loop_graph(ctx)
    config = build_loop_graph_invoke_config(ctx)

    # RFC-622: if the caller flagged this turn as a clarification answer AND
    # the persisted graph state shows a pending clarification with no answer,
    # resume the suspended ``interrupt(...)`` instead of starting a new
    # iteration. Falls back to a normal invocation when no clarification is
    # actually pending (defensive against a stale flag).
    graph_input: dict[str, Any] | Command = {"last_outcome": None}
    answer_text = (ctx.clarification_resume_text or "").strip()
    answer_list = ctx.clarification_resume_answers
    if answer_text or answer_list:
        try:
            snapshot = await compiled.aget_state(config)
            values = getattr(snapshot, "values", {}) or {}
            pending = values.get("pending_clarification")
            answered = values.get("pending_clarification_answer")
            if pending and not answered:
                # Prefer the per-question list when provided so the policy
                # returns answers paired 1:1 with questions instead of
                # broadcasting a single concatenated string. Falls back to
                # the single-string form for legacy single-question turns.
                resume_answers = [str(a) for a in answer_list] if answer_list else [answer_text]
                graph_input = Command(resume={"answers": resume_answers})
                logger.info(
                    "[runner] Resuming pending clarification for loop=%s with %d answer(s)",
                    loop_id,
                    len(resume_answers),
                )
            else:
                logger.warning(
                    "[runner] clarification_answer flag set but no pending clarification "
                    "in state (loop=%s); falling back to normal invocation",
                    loop_id,
                )
        except Exception:
            logger.exception(
                "[runner] failed to read graph state for clarification resume (loop=%s); "
                "falling back to normal invocation",
                loop_id,
            )

    logger.debug("[runner] Starting graph invocation for loop=%s", loop_id)
    try:
        await compiled.ainvoke(graph_input, config=config)
        logger.debug("[runner] Graph invocation completed for loop=%s", loop_id)
    except Exception as e:
        logger.error(
            "[runner] Graph invocation failed for loop=%s: %s\n%s",
            loop_id,
            e,
            traceback.format_exc(),
        )
        raise

    cfg = ctx.strange_loop.config
    if cfg.observability.langfuse.enabled and ctx.goal_trace is not None:
        trace_goal = ctx.loop_state.goal_user_submission or ctx.loop_state.goal
        SootheLangfuse(cfg).patch_goal_io(
            config,
            goal_text=trace_goal,
            output_text=_langfuse_goal_output_text(ctx),
            trace_display_name=loop_graph_langfuse_run_display_name(
                cfg.observability.langfuse.trace_name
            ),
            session_id=ctx.loop_state.thread_id,
        )
