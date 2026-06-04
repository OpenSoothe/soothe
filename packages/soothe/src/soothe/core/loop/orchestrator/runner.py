"""Invoke the compiled Loop graph (RFC-220).

Langfuse (IG-367, IG-396): outer ``ainvoke`` receives the LangChain callback handler so the
Loop Graph run nests planner / CoreAgent spans under one trace; ``langfuse_session_id`` is the
conversation ``thread_id``; Runnable ``configurable.thread_id`` stays ``loop_id`` for checkpoint
routing. Metadata adds ``soothe_component`` and dashboard tags for AgentLoop.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from soothe.core.loop.orchestrator.builder import build_agent_loop_graph
from soothe.core.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.utils.observability.langfuse import (
    loop_graph_langfuse_run_display_name,
    merge_langfuse_runnable_config,
    patch_langfuse_trace_goal_io,
    resolve_langfuse_config_str,
)

logger = logging.getLogger(__name__)


def _langfuse_goal_output_text(ctx: LoopRuntimeContext) -> str:
    """Best-effort final user-visible text for Langfuse trace output (IG-395)."""
    gr = ctx.goal_record
    if gr is not None and (gr.goal_completion or "").strip():
        return gr.goal_completion.strip()
    pp = ctx.loop_state.previous_plan
    if pp is not None:
        if pp.full_output and str(pp.full_output).strip():
            return str(pp.full_output).strip()
        if pp.next_action and str(pp.next_action).strip():
            return str(pp.next_action).strip()
    last = ctx.loop_state.last_execute_assistant_text
    if last and str(last).strip():
        return str(last).strip()
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
    base: dict[str, Any] = {"configurable": {"thread_id": loop_id}}
    # BM-001 fix: propagate workspace to configurable so tools use client workspace
    if ctx.loop_state.workspace:
        base["configurable"]["workspace"] = ctx.loop_state.workspace
    cfg = ctx.agent_loop.config
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
    meta.setdefault("soothe_component", "agent_loop_graph")
    meta.setdefault("soothe_component_version", "agent-loop-v2")
    tags = list(meta.get("langfuse_tags") or [])
    for label in ("goal_execution_loop", "agent-loop-graph"):
        if label not in tags:
            tags.append(label)
    meta["langfuse_tags"] = tags
    out["metadata"] = meta
    return out


async def invoke_agent_loop_graph(ctx: LoopRuntimeContext) -> None:
    """Run the compiled graph once until END.

    Progress is emitted through ``ctx.emit``, which ``AgentLoop.run_with_progress`` wires
    to an asyncio queue consumer.

    Args:
        ctx: Fully initialized runtime context including ``emit``.
    """
    loop_id = ctx.state_manager.loop_id
    planner = ctx.agent_loop.plan_phase._loop_planner
    if hasattr(planner, "_loop_id"):
        planner._loop_id = loop_id

    compiled = build_agent_loop_graph(ctx)
    config = build_loop_graph_invoke_config(ctx)
    logger.debug("[runner] Starting graph invocation for loop=%s", loop_id)
    try:
        await compiled.ainvoke({"last_outcome": None}, config=config)
        logger.debug("[runner] Graph invocation completed for loop=%s", loop_id)
    except Exception as e:
        logger.error(
            "[runner] Graph invocation failed for loop=%s: %s\n%s",
            loop_id,
            e,
            traceback.format_exc(),
        )
        raise

    cfg = ctx.agent_loop.config
    if cfg.observability.langfuse.enabled:
        pub = resolve_langfuse_config_str(cfg.observability.langfuse.public_key)
        trace_goal = ctx.loop_state.goal_user_submission or ctx.loop_state.goal
        patch_langfuse_trace_goal_io(
            config,
            goal_text=trace_goal,
            output_text=_langfuse_goal_output_text(ctx),
            trace_display_name=loop_graph_langfuse_run_display_name(
                cfg.observability.langfuse.trace_name
            ),
            session_id=ctx.loop_state.thread_id,
            public_key=pub,
        )
