"""Wired-subagent intake branch (RFC-630, IG-650 / IG-652).

Catalog wires (``planner``): build the 1-step terminal plan and continue to
``resolve_decision`` → execute → ``goal_completion``.

Intake-only wires (``browser_use``, ``deep_research``, ``academic_research``):
invoke the specialist runnable from the intake-only registry (not on CoreAgent
``task``), record Human/AI execute-step ledger rows, then route to
``goal_completion``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.foundation.sloop.goal_text import resolve_user_request
from soothe.foundation.sloop.state.schemas import is_intake_only_wire_subagent
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

WIRED_SUBAGENT_STATUS_LABEL = "Delegating to {subagent}"


def _extract_subagent_report(result: Any) -> str:
    """Mirror SubAgentMiddleware return text (structured_response or last AI)."""
    if not isinstance(result, dict):
        return (str(result) if result is not None else "").strip()

    structured = result.get("structured_response")
    if structured is not None:
        if hasattr(structured, "model_dump_json"):
            return str(structured.model_dump_json()).strip()
        if hasattr(structured, "model_dump"):
            return json.dumps(structured.model_dump()).strip()
        if isinstance(structured, (dict, list)):
            return json.dumps(structured).strip()
        return str(structured).strip()

    messages = result.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                text = (msg.text or "").rstrip() if hasattr(msg, "text") else ""
                if not text:
                    text = extract_text_from_message_content(getattr(msg, "content", None)).strip()
                if text:
                    return text
    return ""


def _record_wired_execute_ledger(
    ctx: LoopRuntimeContext,
    *,
    goal_text: str,
    report: str,
    wire: str,
    step_id: str,
) -> None:
    """Write execute-step Human/AI so ``ledger_direct`` can surface the report."""
    state = ctx.loop_state
    human = LoopHumanMessage(
        content=goal_text,
        thread_id=getattr(state, "thread_id", None),
        iteration=getattr(state, "iteration", 0),
        goal_summary=(goal_text[:200] if goal_text else None),
        workspace=getattr(state, "workspace", None),
        phase="execute_step",
        step_id=step_id,
    )
    ai = LoopAIMessage(
        content=report,
        thread_id=getattr(state, "thread_id", None),
        iteration=getattr(state, "iteration", 0),
        phase="execute_step",
        step_id=step_id,
    )
    if ctx.ce is not None:
        from soothe.foundation.sloop.utils.messages import _record_ledger_message

        _record_ledger_message(ctx.ce, human, "execute_step")
        _record_ledger_message(ctx.ce, ai, "execute_step")
        return

    # Tests / unbound CE: keep cache warm for last_ledger_ai_content.
    cache = getattr(state, "_loop_messages_cache", None)
    if isinstance(cache, list):
        cache.extend([human, ai])
    else:
        logger.debug(
            "[WiredSubagent] No CE and no loop_messages cache; report not ledgered (subagent=%s)",
            wire,
        )


async def _invoke_intake_only_direct(
    ctx: LoopRuntimeContext,
    *,
    wire: str,
    goal_text: str,
) -> dict[str, Any]:
    """Run intake-only CompiledSubAgent and hand off to goal_completion (IG-652)."""
    lookup = getattr(ctx.core_agent, "lookup_intake_only_subagent", None)
    spec = lookup(wire) if callable(lookup) else None
    if spec is None:
        logger.error("[WiredSubagent] Intake-only specialist not registered: %s", wire)
        await ctx.emit(
            "fatal_error",
            {"error": f"Intake-only subagent not available: {wire}", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    runnable = spec.get("runnable") if isinstance(spec, dict) else getattr(spec, "runnable", None)
    if runnable is None or not hasattr(runnable, "ainvoke"):
        logger.error("[WiredSubagent] Intake-only spec missing runnable: %s", wire)
        await ctx.emit(
            "fatal_error",
            {"error": f"Intake-only subagent has no runnable: {wire}", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    intent = ctx.loop_state.intent
    plan = build_trivial_plan(
        goal_text,
        wire_subagent=wire,
        requires_tool_use=bool(getattr(intent, "requires_tool_use", True)),
    )
    ctx.scratch.plan_result = plan
    step = plan.decision.steps[0]
    step_id = step.id

    try:
        result = await runnable.ainvoke({"messages": [HumanMessage(content=goal_text)]})
    except Exception as exc:
        logger.exception("[WiredSubagent] Direct invoke failed (subagent=%s)", wire)
        await ctx.emit(
            "fatal_error",
            {"error": f"Wired subagent failed: {type(exc).__name__}: {exc}", "step_id": step_id},
        )
        return {"last_outcome": "fatal"}

    report = _extract_subagent_report(result)
    if not report.strip():
        report = f"({wire} completed with no text output)"

    _record_wired_execute_ledger(
        ctx, goal_text=goal_text, report=report, wire=wire, step_id=step_id
    )
    logger.info(
        "[WiredSubagent] Intake-only direct invoke done (subagent=%s chars=%d)",
        wire,
        len(report),
    )
    # Do not set after_record_route — that flag means record_iteration already
    # advanced the counter. Direct intake-only skips record_iteration.
    return {"wired_route_next": "goal_completion"}


async def node_invoke_wired_subagent(
    ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Resolve wire and either direct-invoke (intake-only) or inject planner plan."""
    intent = ctx.loop_state.intent
    wire = resolve_user_requested_wire_subagent(
        routing_classification=ctx.loop_state.routing_classification,
        intent=intent,
        preferred_subagent=getattr(ctx, "preferred_subagent", None),
    )
    if not wire:
        logger.error("[WiredSubagent] Missing resolved wire_subagent; aborting branch")
        await ctx.emit(
            "fatal_error",
            {"error": "Wired subagent route without a resolved specialist", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    goal_text = resolve_user_request(ctx.loop_state) or ctx.loop_state.goal
    label = WIRED_SUBAGENT_STATUS_LABEL.format(subagent=wire)
    await ctx.emit(
        "plan_phase_status",
        {
            "label": label,
            "total_tokens_used": ctx.loop_state.total_tokens_used,
        },
    )

    if is_intake_only_wire_subagent(wire):
        return await _invoke_intake_only_direct(ctx, wire=wire, goal_text=goal_text)

    # Dual-exposed catalog wire (planner): trivial plan → resolve → execute.
    ctx.scratch.plan_result = build_trivial_plan(
        goal_text,
        wire_subagent=wire,
        requires_tool_use=bool(getattr(intent, "requires_tool_use", True)),
    )
    logger.info(
        "[WiredSubagent] Catalog wire ready (subagent=%s goal=%s)",
        wire,
        goal_text[:50],
    )
    return {}
