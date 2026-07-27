"""Wired-subagent intake branch (RFC-630, IG-599 / IG-601 / IG-602 / IG-656).

Intake-only wires (``planner``, ``browser_use``, ``deep_research``,
``academic_research``): stream the specialist runnable from the intake-only
registry (not on CoreAgent ``task``), forward curated wire customs for the
orphan SubAgent card, record Human/AI execute-step ledger rows, then route to
``goal_completion``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from soothe.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.goal_text import resolve_user_request
from soothe.sloop.state.schemas import is_intake_only_wire_subagent
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.sloop.utils.stream_normalize import extract_text_from_message_content

from ..orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

WIRED_SUBAGENT_STATUS_LABEL = "Delegating to {subagent}"
_DESC_DISPLAY_MAX = 200


def _extract_subagent_report(result: Any) -> str:
    """Mirror SubAgentMiddleware return text, plus CompiledSubAgent ``answer``.

    Intake-only specialists write the user-facing report to state ``answer``
    (and usually mirror it on an ``AIMessage`` in ``messages``).
    """
    if not isinstance(result, dict):
        return (str(result) if result is not None else "").strip()

    answer = result.get("answer")
    if answer is not None:
        text = answer.strip() if isinstance(answer, str) else str(answer).strip()
        if text:
            return text

    messages = result.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                text = (msg.text or "").rstrip() if hasattr(msg, "text") else ""
                if not text:
                    text = extract_text_from_message_content(getattr(msg, "content", None)).strip()
                if text:
                    return text

    # Last resort: stringify structured payload only when no textual report exists.
    structured = result.get("structured_response")
    if structured is not None:
        if hasattr(structured, "model_dump_json"):
            return str(structured.model_dump_json()).strip()
        if hasattr(structured, "model_dump"):
            return str(structured.model_dump()).strip()
        return str(structured).strip()
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
        from soothe.sloop.utils.messages import _record_ledger_message

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


def _unpack_astream_item(item: Any) -> tuple[str | None, Any]:
    """Normalize LangGraph ``astream`` items to ``(mode, data)``."""
    if isinstance(item, tuple):
        if len(item) == 2:
            mode, data = item
            return (str(mode) if mode is not None else None), data
        if len(item) == 3:
            _ns, mode, data = item
            return (str(mode) if mode is not None else None), data
    return None, item


async def _forward_wire_custom(
    ctx: LoopRuntimeContext,
    data: dict[str, Any],
    *,
    invocation_id: str,
    step_id: str,
) -> None:
    """Stamp and forward curated ``soothe.subagent.*`` customs to the query stream."""
    et = data.get("type")
    if not isinstance(et, str) or not et.startswith("soothe.subagent."):
        return
    stamped = {**data, "invocation_id": invocation_id, "step_id": step_id}
    await ctx.emit("stream_event", ((), "custom", stamped))


async def _run_intake_only_runnable(
    ctx: LoopRuntimeContext,
    runnable: Any,
    *,
    goal_text: str,
    invocation_id: str,
    step_id: str,
) -> Any:
    """Run specialist while bridging wire customs live onto the query stream.

    LangGraph ``get_stream_writer`` is often unavailable inside long single-node
    specialists (notably browser_use): emits land in the runner log only. Install a
    wire bridge so ``emit_progress`` posts to a queue drained concurrently for live
    orphan-card activity. Stream ``values`` (or ``ainvoke``) for the final state.
    """
    from soothe_nano.utils.progress import reset_wire_bridge, set_wire_bridge

    input_state = {"messages": [HumanMessage(content=goal_text)]}
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _bridge_sink(event: dict[str, Any]) -> None:
        payload = dict(event)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            queue.put_nowait(payload)
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            logger.debug("[WiredSubagent] bridge sink dropped event: loop closed")

    async def _drain_bridge() -> None:
        while True:
            item = await queue.get()
            if item is None:
                return
            try:
                await _forward_wire_custom(ctx, item, invocation_id=invocation_id, step_id=step_id)
            except Exception:
                logger.debug("[WiredSubagent] bridge forward failed", exc_info=True)

    bridge_token = set_wire_bridge(_bridge_sink)
    drain_task = asyncio.create_task(_drain_bridge())
    try:
        astream = getattr(runnable, "astream", None)
        if callable(astream):
            last_values: Any = None
            try:
                # Customs arrive via the wire bridge; only consume final state here.
                stream = astream(input_state, stream_mode=["values"])
                async for item in stream:
                    mode, data = _unpack_astream_item(item)
                    if mode == "values" or mode is None:
                        last_values = data
                if last_values is not None:
                    return last_values
            except TypeError:
                logger.debug(
                    "[WiredSubagent] astream(stream_mode=values) unsupported; "
                    "falling back to ainvoke",
                    exc_info=True,
                )
        return await runnable.ainvoke(input_state)
    finally:
        await queue.put(None)
        try:
            # Keep draining queued wire events even if the caller is cancelled.
            await asyncio.shield(drain_task)
        finally:
            reset_wire_bridge(bridge_token)


async def _invoke_intake_only_direct(
    ctx: LoopRuntimeContext,
    *,
    wire: str,
    goal_text: str,
) -> dict[str, Any]:
    """Run intake-only CompiledSubAgent with orphan-card stream bridge (IG-602)."""
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
    invocation_id = uuid.uuid4().hex[:12]
    description = (goal_text or "").strip()
    if len(description) > _DESC_DISPLAY_MAX:
        description = description[: _DESC_DISPLAY_MAX - 1] + "…"

    await ctx.emit(
        "wired_subagent_started",
        {
            "subagent": wire,
            "invocation_id": invocation_id,
            "step_id": step_id,
            "description": description,
        },
    )

    started_at = time.monotonic()
    try:
        result = await _run_intake_only_runnable(
            ctx,
            runnable,
            goal_text=goal_text,
            invocation_id=invocation_id,
            step_id=step_id,
        )
    except asyncio.CancelledError:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        await ctx.emit(
            "wired_subagent_cancelled",
            {
                "subagent": wire,
                "invocation_id": invocation_id,
                "step_id": step_id,
                "duration_ms": duration_ms,
                "summary": "Cancelled",
            },
        )
        raise
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        logger.exception("[WiredSubagent] Direct invoke failed (subagent=%s)", wire)
        await ctx.emit(
            "wired_subagent_failed",
            {
                "subagent": wire,
                "invocation_id": invocation_id,
                "step_id": step_id,
                "duration_ms": duration_ms,
                "summary": f"{type(exc).__name__}: {exc}",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        await ctx.emit(
            "fatal_error",
            {"error": f"Wired subagent failed: {type(exc).__name__}: {exc}", "step_id": step_id},
        )
        return {"last_outcome": "fatal"}

    duration_ms = int((time.monotonic() - started_at) * 1000)
    report = _extract_subagent_report(result)
    if not report.strip():
        report = f"({wire} completed with no text output)"

    _record_wired_execute_ledger(
        ctx, goal_text=goal_text, report=report, wire=wire, step_id=step_id
    )
    card_summary = report.strip().splitlines()[0][:160] if report.strip() else "Done"
    await ctx.emit(
        "wired_subagent_completed",
        {
            "subagent": wire,
            "invocation_id": invocation_id,
            "step_id": step_id,
            "duration_ms": duration_ms,
            "summary": card_summary,
        },
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
    """Resolve wire and direct-invoke the intake-only specialist."""
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

    if not is_intake_only_wire_subagent(wire):
        logger.error(
            "[WiredSubagent] Unexpected non-intake wire=%s; all allowlisted "
            "specialists are intake-only",
            wire,
        )
        await ctx.emit(
            "fatal_error",
            {
                "error": f"Wired subagent is not intake-only: {wire}",
                "step_id": "",
            },
        )
        return {"last_outcome": "fatal"}

    return await _invoke_intake_only_direct(ctx, wire=wire, goal_text=goal_text)
