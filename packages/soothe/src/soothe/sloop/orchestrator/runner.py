"""Invoke the compiled Strange Loop graph."""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any

from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.checkpoint import (
    strange_loop_configurable,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.utils.plan_action_text import resolve_plan_action_text
from soothe.utils.observability.langfuse import (
    SootheLangfuse,
    loop_graph_langfuse_run_display_name,
    merge_langfuse_runnable_config,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _langfuse_goal_output_text(ctx: LoopRuntimeContext) -> str:
    """Best-effort final user-visible text for Langfuse trace output."""
    from soothe.sloop.engine.completion.continuation_context import ledger_goal_completion_text
    from soothe.sloop.intention.models import IntakeLabel

    completion = ledger_goal_completion_text(ctx.loop_state.loop_messages)
    if completion:
        return completion

    intent = getattr(ctx.loop_state, "intent", None)
    if intent is not None and getattr(intent, "intake_label", None) == IntakeLabel.CHITCHAT:
        chitchat_response = (getattr(intent, "chitchat_response", None) or "").strip()
        if chitchat_response:
            return chitchat_response
    pp = ctx.loop_state.previous_plan
    if pp is not None:
        if pp.full_output and str(pp.full_output).strip():
            return str(pp.full_output).strip()
        action_text = resolve_plan_action_text(pp)
        if action_text:
            return action_text
    return ""


def build_loop_graph_invoke_config(ctx: LoopRuntimeContext) -> dict[str, Any]:
    """Build RunnableConfig for `CompiledGraph.ainvoke`."""
    loop_id = ctx.state_manager.loop_id
    extra: dict[str, Any] = {}
    if ctx.loop_state.workspace:
        extra["workspace"] = ctx.loop_state.workspace
    configurable = strange_loop_configurable(loop_id, **extra)

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

    When a clarification answer is provided, uses the unified relay to
    submit the answer and build the resume directive. The graph is
    re-invoked with `graph_input` (not `Command(resume=...)` at the
    StrangeLoop level — the graph was not interrupted, it exited cleanly).
    """
    loop_id = ctx.state_manager.loop_id

    compiled = build_strange_loop_graph(ctx)
    config = build_loop_graph_invoke_config(ctx)

    graph_input: dict[str, Any] = {"last_outcome": None}
    answer_text = (ctx.clarification_resume_text or "").strip()
    answer_list = ctx.clarification_resume_answers
    if answer_text or answer_list:
        try:
            resume_answers = [str(a) for a in answer_list] if answer_list else [answer_text]
            if ctx.relay is not None:
                rows = await ctx.relay.store.list_by_loop(loop_id, status="parked")
                if rows:
                    relay_id = rows[0].relay_id
                    await ctx.relay.submit_answer(
                        relay_id=relay_id,
                        answers=resume_answers,
                        source="human",
                        ce=ctx.ce,
                    )
                    directive = await ctx.relay.build_resume_directive(
                        relay_id=relay_id,
                        ce=ctx.ce,
                    )
                    graph_input = directive.graph_input
                    logger.info(
                        "[runner] relay resume relay_id=%s station=%s",
                        relay_id[:12],
                        directive.resume_station,
                    )
                else:
                    logger.warning(
                        "[runner] relay resume: no parked rows (loop=%s); "
                        "falling back to normal invocation",
                        loop_id,
                    )
            else:
                logger.warning(
                    "[runner] clarification_answer but no relay (loop=%s); "
                    "falling back to normal invocation",
                    loop_id,
                )
        except Exception:
            logger.exception(
                "[runner] clarification resume failed (loop=%s); falling back to normal invocation",
                loop_id,
            )

    logger.info(
        "[runner] Graph invoke start loop_id=%s thread_id=%s resume=%s",
        loop_id,
        ctx.loop_state.thread_id,
        "resume_relay_id" in graph_input,
    )
    from soothe.sloop.utils.token_usage import loop_token_accumulation_scope

    try:
        with loop_token_accumulation_scope(ctx.loop_state):
            await compiled.ainvoke(graph_input, config=config)
        logger.info("[runner] Graph invoke complete loop_id=%s", loop_id)
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
