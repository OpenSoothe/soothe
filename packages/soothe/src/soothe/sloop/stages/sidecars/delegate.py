"""Wired-subagent intake branch (RFC-630, IG-599 / IG-601 / IG-602 / IG-656 / IG-658 / IG-660).

Intake-only wires (``planner``, ``browser_use``, ``deep_research``,
``academic_research``): stream the specialist runnable from the intake-only
registry (not on CoreAgent ``task``), forward curated wire customs for the
orphan SubAgent card, record Human/AI execute-step ledger rows.

For ``planner`` (RFC-633 / IG-660): persist ``.soothe/plans/`` artifact and pause
on RFC-622 clarification (Approve / Reject / More comments). Approve hands off
to StrangeLoop ``plan_generate``; Reject routes to ``goal_completion``. Other
wires still route directly to ``goal_completion``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from soothe.sloop.clarification.origins import (
    ORIGIN_PLANNER_SUBAGENT_REVIEW,
    PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX,
    PLANNER_WIRE_SUBAGENT,
)
from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
    answer_from_state,
    request_to_state,
)
from soothe.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.goal_text import resolve_user_request
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.plans.artifact import (
    parse_planner_subagent_review_answers,
    strip_plan_frontmatter,
    update_plan_artifact_status,
    write_plan_artifact,
)
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.sloop.utils.stream_normalize import extract_text_from_message_content

logger = logging.getLogger(__name__)

WIRED_SUBAGENT_STATUS_LABEL = "Delegating to {subagent}"
_DESC_DISPLAY_MAX = 200
_PLANNER_SUBAGENT_REVIEW_QUESTIONS: tuple[str, ...] = (
    "Action for this plan: Approve, Reject, or More comments",
    "Revision comments (when choosing More comments)",
)


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

    structured = result.get("structured_response")
    if structured is not None:
        if hasattr(structured, "model_dump_json"):
            return str(structured.model_dump_json()).strip()
        if hasattr(structured, "model_dump"):
            return str(structured.model_dump()).strip()
        return str(structured).strip()
    return ""


def _build_loop_state_view(ctx: LoopRuntimeContext) -> LoopStateView:
    state = ctx.loop_state
    goal_record = getattr(ctx, "goal_record", None)
    user_request = resolve_user_request(state)
    plan_path = getattr(ctx.scratch, "plan_artifact_path", None)
    plan_summary = plan_path or getattr(ctx.scratch, "plan_artifact_markdown", None)
    if isinstance(plan_summary, str) and len(plan_summary) > 400:
        plan_summary = plan_summary[:400] + "…"
    return LoopStateView(
        goal_id=getattr(goal_record, "goal_id", "") or "",
        goal_description=user_request,
        user_request=user_request,
        iteration=getattr(state, "iteration", 0),
        intent_classification=getattr(state, "intent_classification", None),
        plan_summary=plan_summary,
        recent_step_outputs=(),
        workspace_summary=getattr(state, "workspace", None),
        active_skills=tuple(getattr(state, "activated_skill_names", []) or []),
        active_mcp_servers=tuple(getattr(state, "active_mcp_servers", []) or []),
    )


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
    """Stamp and forward curated customs (subagent + tool_call.update) to the stream."""
    from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

    et = data.get("type")
    if not isinstance(et, str):
        return
    if et == STREAM_TOOL_CALL_UPDATE:
        raw_id = str(data.get("tool_call_id") or "").strip() or uuid.uuid4().hex[:12]
        if ":" not in raw_id and step_id:
            stamped_id = f"{step_id}:s:{raw_id}"
        else:
            stamped_id = raw_id
        stamped = {
            **data,
            "tool_call_id": stamped_id,
            "invocation_id": invocation_id,
            "step_id": step_id,
        }
        await ctx.emit("stream_event", ((), "custom", stamped))
        return
    if not et.startswith("soothe.subagent."):
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
    wire: str,
) -> Any:
    """Run specialist while bridging wire customs live onto the query stream."""
    from soothe_nano.utils.progress import reset_wire_bridge, set_wire_bridge

    from soothe.sloop.orchestrator.checkpoint_keys import intake_only_invoke_config

    state_manager = getattr(ctx, "state_manager", None)
    loop_id = str(getattr(state_manager, "loop_id", "") or "")
    if not loop_id:
        loop_state = getattr(ctx, "loop_state", None)
        loop_id = str(getattr(loop_state, "thread_id", "") or "") or "loop"
    workspace = getattr(getattr(ctx, "loop_state", None), "workspace", None)
    run_config = intake_only_invoke_config(
        loop_id,
        wire,
        workspace=str(workspace) if workspace else None,
    )

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
                stream = astream(input_state, config=run_config, stream_mode=["values"])
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
        return await runnable.ainvoke(input_state, config=run_config)
    finally:
        await queue.put(None)
        try:
            await asyncio.shield(drain_task)
        finally:
            reset_wire_bridge(bridge_token)


def _planner_goal_text(ctx: LoopRuntimeContext, base: str) -> str:
    """Append prior plan + review comments when refining after More comments."""
    parts = [base.strip()] if base.strip() else []
    comments = (getattr(ctx.scratch, "planner_subagent_review_comments", None) or "").strip()
    prior = (getattr(ctx.scratch, "plan_artifact_markdown", None) or "").strip()
    path = (getattr(ctx.scratch, "plan_artifact_path", None) or "").strip()
    if comments:
        parts.append(f"## Human review comments\n{comments}")
    if prior:
        parts.append(f"## Prior plan draft\n{prior}")
    if path:
        parts.append(f"## Prior plan file\n{path}")
    return "\n\n".join(parts) if parts else base


def _save_planner_artifact(ctx: LoopRuntimeContext, report: str) -> str | None:
    workspace = getattr(ctx.loop_state, "workspace", None) or ""
    if not str(workspace).strip():
        logger.warning("[WiredSubagent] No workspace; skipping plan artifact write")
        return None
    goal_record = getattr(ctx, "goal_record", None)
    try:
        path = write_plan_artifact(
            workspace,
            report,
            title=resolve_user_request(ctx.loop_state) or ctx.loop_state.goal or "plan",
            goal_id=getattr(goal_record, "goal_id", "") or "",
            loop_id=str(getattr(ctx.loop_state, "thread_id", "") or ""),
            status="draft",
        )
    except OSError:
        logger.exception("[WiredSubagent] Failed to write plan artifact")
        return None
    ctx.scratch.plan_artifact_path = str(path)
    ctx.scratch.plan_artifact_markdown = report
    logger.info("[WiredSubagent] Plan artifact written: %s", path)
    return str(path)


def _planner_subagent_review_pending_payload(ctx: LoopRuntimeContext) -> dict[str, Any]:
    """Build pending clarification after planner artifact write.

    Persist ``plan_path`` / ``plan_markdown`` on the pending channel so a
    clarification-resume turn (fresh scratch) can still emit or hydrate the
    plan body. ``await_clarification`` also reads scratch when present.
    """
    req = ClarificationRequest(
        questions=_PLANNER_SUBAGENT_REVIEW_QUESTIONS,
        origin_node=ORIGIN_PLANNER_SUBAGENT_REVIEW,
        origin_interrupt_id=(f"{PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX}{uuid.uuid4().hex[:8]}"),
        loop_state=_build_loop_state_view(ctx),
    )
    pending = request_to_state(req)
    path = (getattr(ctx.scratch, "plan_artifact_path", None) or "").strip()
    markdown = (getattr(ctx.scratch, "plan_artifact_markdown", None) or "").strip()
    if path:
        pending["plan_path"] = path
    if markdown:
        pending["plan_markdown"] = markdown
    return {
        "pending_clarification": pending,
        "last_clarification_origin": ORIGIN_PLANNER_SUBAGENT_REVIEW,
        "pending_clarification_answer": None,
    }


def _hydrate_planner_scratch_from_pending(ctx: LoopRuntimeContext, state: dict[str, Any]) -> None:
    """Restore plan artifact onto scratch after a clarification-resume turn."""
    pending = state.get("pending_clarification")
    if not isinstance(pending, dict):
        return
    path = str(pending.get("plan_path") or "").strip()
    markdown = str(pending.get("plan_markdown") or "").strip()
    if path and not (getattr(ctx.scratch, "plan_artifact_path", None) or "").strip():
        ctx.scratch.plan_artifact_path = path
    if markdown and not (getattr(ctx.scratch, "plan_artifact_markdown", None) or "").strip():
        ctx.scratch.plan_artifact_markdown = markdown
    if not (getattr(ctx.scratch, "plan_artifact_markdown", None) or "").strip() and path:
        try:
            from pathlib import Path

            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            logger.debug("[WiredSubagent] could not reload plan artifact %s", path, exc_info=True)
        else:
            ctx.scratch.plan_artifact_markdown = text
            ctx.scratch.plan_artifact_path = path


async def _handle_planner_subagent_review_answer(
    ctx: LoopRuntimeContext,
    state: dict[str, Any],
    *,
    wire: str,
    goal_text: str,
) -> dict[str, Any]:
    """Resume after planner-subagent review: approve, reject, or re-plan with comments."""
    _hydrate_planner_scratch_from_pending(ctx, state)
    raw_answer = state.get("pending_clarification_answer")
    try:
        answer = answer_from_state(raw_answer or {})
    except ValueError:
        logger.exception("[WiredSubagent] malformed planner-subagent review answer")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "fatal",
        }

    action, comments = parse_planner_subagent_review_answers(answer.answers)
    path = getattr(ctx.scratch, "plan_artifact_path", None)
    report = (getattr(ctx.scratch, "plan_artifact_markdown", None) or "").strip()

    # Clarification-resume turns rebuild LoopPhaseScratch; reinject a trivial
    # plan so Reject → goal_completion can ledger_direct without a fatal.
    # Approve clears plan_result and hands off to StrangeLoop plan_generate.
    if ctx.scratch.plan_result is None:
        ctx.scratch.plan_result = build_trivial_plan(
            goal_text,
            wire_subagent=wire,
            requires_tool_use=False,
        )

    step_id = "PLAN-RV"
    if ctx.scratch.plan_result and getattr(ctx.scratch.plan_result, "decision", None):
        steps = getattr(ctx.scratch.plan_result.decision, "steps", None) or []
        if steps:
            step_id = steps[0].id

    if action == "approve":
        if path:
            update_plan_artifact_status(path, "approved")
        # Short note only — full body stays on scratch for plan_generate grounding.
        note = "Plan approved. Proceeding to implement."
        if path:
            note = f"{note}\n\nSaved to: `{path}`"
        _record_wired_execute_ledger(
            ctx, goal_text=goal_text, report=note, wire=wire, step_id=step_id
        )
        from soothe.sloop.stages.plan.gather_evidence import _create_fresh_loop_assessment

        # StrangeLoop will own the decision; drop the intake trivial plan.
        ctx.scratch.plan_result = None
        ctx.scratch.plan_assessment = _create_fresh_loop_assessment()
        ctx.scratch.planner_subagent_review_comments = None
        ctx.scratch.planner_implement_handoff = True
        ctx.preferred_subagent = None
        body = strip_plan_frontmatter(report) if report else ""
        if not body and path:
            body = strip_plan_frontmatter(
                getattr(ctx.scratch, "plan_artifact_markdown", None) or ""
            )
        state_obj = ctx.loop_state
        if state_obj is not None:
            state_obj.approved_plan_path = str(path) if path else None
            state_obj.approved_plan_markdown = body or None
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
            "planner_implement_handoff": True,
            "intent_route": None,
        }

    if action == "reject":
        if path:
            update_plan_artifact_status(path, "rejected")
        final = "Plan rejected by operator."
        if path:
            final = f"{final}\n\nPlan file (rejected): `{path}`"
        if comments:
            final = f"{final}\n\nComments: {comments}"
        _record_wired_execute_ledger(
            ctx, goal_text=goal_text, report=final, wire=wire, step_id=step_id
        )
        ctx.scratch.planner_subagent_review_comments = None
        ctx.scratch.planner_implement_handoff = False
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
            "planner_implement_handoff": False,
        }

    ctx.scratch.planner_subagent_review_comments = comments
    return await _invoke_intake_only_direct(
        ctx,
        wire=wire,
        goal_text=_planner_goal_text(ctx, goal_text),
    )


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
    logger.info(
        "[WiredSubagent] invoke %s step=%s inv=%s chars=%d",
        wire,
        step_id,
        invocation_id,
        len(goal_text or ""),
    )

    started_at = time.monotonic()
    try:
        result = await _run_intake_only_runnable(
            ctx,
            runnable,
            goal_text=goal_text,
            invocation_id=invocation_id,
            step_id=step_id,
            wire=wire,
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

    logger.info(
        "[WiredSubagent] done %s step=%s ms=%d chars=%d",
        wire,
        step_id,
        duration_ms,
        len(report),
    )

    review = wire == PLANNER_WIRE_SUBAGENT
    if review:
        _save_planner_artifact(ctx, report)

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
        "[WiredSubagent] Intake-only direct invoke done (subagent=%s chars=%d review=%s)",
        wire,
        len(report),
        review,
    )
    if review:
        return _planner_subagent_review_pending_payload(ctx)
    return {}


async def node_invoke_wired_subagent(
    ctx: LoopRuntimeContext, state: dict[str, Any]
) -> dict[str, Any]:
    """Resolve wire and direct-invoke the intake-only specialist."""
    goal_text = resolve_user_request(ctx.loop_state) or ctx.loop_state.goal

    # Clarification resume re-enters this node without Pass2 wire resolution —
    # honor planner review answers before requiring a live wire_subagent.
    if (
        state.get("pending_clarification_answer")
        and state.get("last_clarification_origin") == ORIGIN_PLANNER_SUBAGENT_REVIEW
    ):
        return await _handle_planner_subagent_review_answer(
            ctx, state, wire=PLANNER_WIRE_SUBAGENT, goal_text=goal_text
        )

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

    label = WIRED_SUBAGENT_STATUS_LABEL.format(subagent=wire)
    await emit_plan_phase_status(ctx, label=label)
    return await _invoke_intake_only_direct(ctx, wire=wire, goal_text=goal_text)
