"""Invoke the compiled Loop graph (RFC-620).

Langfuse (IG-367): outer ``ainvoke`` receives the same LangChain callback handler as other
LangGraph streams; ``langfuse_session_id`` uses the conversation ``thread_id`` so planner /
execute / loop orchestration traces share one session; Runnable ``thread_id`` remains
``loop_id`` for LangGraph checkpoint routing.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.agent_loop.graph.builder import build_agent_loop_graph
from soothe.core.agent_loop.graph.runtime_context import LoopRuntimeContext
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config

logger = logging.getLogger(__name__)


def build_loop_graph_invoke_config(ctx: LoopRuntimeContext) -> dict[str, Any]:
    """Build RunnableConfig for ``CompiledGraph.ainvoke`` with Langfuse + loop metadata.

    Configurable ``thread_id`` is ``loop_id`` (RFC-620). Langfuse session correlation uses
    ``loop_state.thread_id`` so traces align with planner LLM and CoreAgent execute streams.

    Args:
        ctx: Runtime context for the current goal run.

    Returns:
        RunnableConfig dict safe to pass to ``ainvoke``.
    """
    loop_id = ctx.state_manager.loop_id
    base: dict[str, Any] = {"configurable": {"thread_id": loop_id}}
    cfg = ctx.agent_loop.config
    tn = (cfg.observability.langfuse.trace_name or "").strip()
    run_name = f"{tn}:agent-loop-graph" if tn else "agent-loop-graph"
    merged = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id=ctx.loop_state.thread_id,
        run_name=run_name,
    )
    out = dict(merged)
    meta = dict(out.get("metadata") or {})
    meta.setdefault("loop_id", loop_id)
    out["metadata"] = meta
    return out


async def invoke_agent_loop_graph(ctx: LoopRuntimeContext) -> None:
    """Run the compiled graph once until END.

    Progress is emitted through ``ctx.emit``, which ``AgentLoop.run_with_progress`` wires
    to an asyncio queue consumer.

    Args:
        ctx: Fully initialized runtime context including ``emit``.
    """
    compiled = build_agent_loop_graph(ctx)
    config = build_loop_graph_invoke_config(ctx)
    await compiled.ainvoke({"last_outcome": None}, config=config)
