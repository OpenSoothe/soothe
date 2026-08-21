"""Plan-mode review host module: approve / reject / comment for plan mode.

When ``interaction_mode == "plan"`` and a plan draft is ready, this module
builds a clarification request (origin ``ORIGIN_PLAN_MODE_REVIEW``) that
pauses execution for user input on critical design points.

On fresh plan review:
    - Collect the plan draft from the step's final AI message.
    - Write the plan to ``.soothe/plans/`` via ``save_plan_draft``.
    - Record a ``goal_completion`` ledger pair: Human = goal text,
      AI = plan body (the synthesized plan, not intermediate step messages).
    - Emit the approve/reject/comment clarification.

On approve:
    - Set ``LoopState.approved_plan_markdown`` + ``LoopState.approved_plan_path``
      so the existing DISPATCH grounding chain consumes it.
    - Record the user's action as a new ``goal_completion`` AI message:
      "Plan approved by operator." (so subsequent goals see the approval in
      the ledger).

On reject:
    - Record "Plan rejected by operator." as a ``goal_completion`` AI message.

On comment:
    - Record "Plan revision requested: <comments>" as a ``goal_completion``
      AI message.
    - Re-emit the plan review clarification for the next iteration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from soothe.sloop.clarification.origins import (
    ORIGIN_PLAN_MODE_REVIEW,
)
from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
    request_to_state,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.plans.artifact import (
    parse_plan_review_answers,
    strip_plan_frontmatter,
    update_plan_artifact_status,
    write_plan_artifact,
)
from soothe.sloop.plans.plan_synthesizer import synthesize_plan
from soothe.sloop.utils.goal_text import resolve_user_request

logger = logging.getLogger(__name__)

_PLAN_MODE_REVIEW_QUESTIONS: tuple[str, ...] = (
    "Action for this plan: Approve, Reject, or More comments",
    "Revision comments (when choosing More comments)",
)

_PLAN_MODE_REVIEW_INTERRUPT_PREFIX = "plan-mode-review:"


def _build_loop_state_view(ctx: LoopRuntimeContext) -> LoopStateView:
    """Build a snapshot of the loop state for the clarification request."""
    state = ctx.loop_state
    goal_record = getattr(ctx, "goal_record", None)
    user_request = resolve_user_request(state)
    plan_path = getattr(ctx.scratch, "plan_draft_path", None)
    plan_summary = plan_path or getattr(ctx.scratch, "plan_draft_markdown", None)
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


def save_plan_draft(ctx: LoopRuntimeContext, report: str) -> str | None:
    """Write the plan draft to ``.soothe/plans/`` and store on scratch."""
    workspace = getattr(ctx.loop_state, "workspace", None) or ""
    if not str(workspace).strip():
        logger.warning("[PlanModeReview] No workspace; skipping plan artifact write")
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
        logger.exception("[PlanModeReview] Failed to write plan artifact")
        return None
    ctx.scratch.plan_draft_path = str(path)
    ctx.scratch.plan_draft_markdown = report
    logger.info("[PlanModeReview] Plan artifact written: %s", path)
    return str(path)


def build_plan_mode_review_pending(ctx: LoopRuntimeContext) -> dict[str, Any]:
    """Build the pending clarification payload for plan-mode review.

    Persist ``plan_path`` / ``plan_markdown`` on the pending channel so a
    clarification-resume turn (fresh scratch) can still hydrate the plan body.
    """
    req = ClarificationRequest(
        questions=_PLAN_MODE_REVIEW_QUESTIONS,
        origin_node=ORIGIN_PLAN_MODE_REVIEW,
        origin_interrupt_id=(f"{_PLAN_MODE_REVIEW_INTERRUPT_PREFIX}{uuid.uuid4().hex[:8]}"),
        loop_state=_build_loop_state_view(ctx),
    )
    pending = request_to_state(req)
    path = (getattr(ctx.scratch, "plan_draft_path", None) or "").strip()
    markdown = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if path:
        pending["plan_path"] = path
    if markdown:
        pending["plan_markdown"] = markdown
    return {
        "pending_clarification": pending,
        "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
        "pending_clarification_answer": None,
    }


def hydrate_scratch_from_pending(ctx: LoopRuntimeContext, state: dict[str, Any]) -> None:
    """Restore plan draft onto scratch after a clarification-resume turn."""
    pending = state.get("pending_clarification")
    if not isinstance(pending, dict):
        return
    path = str(pending.get("plan_path") or "").strip()
    markdown = str(pending.get("plan_markdown") or "").strip()
    if path and not (getattr(ctx.scratch, "plan_draft_path", None) or "").strip():
        ctx.scratch.plan_draft_path = path
    if markdown and not (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip():
        ctx.scratch.plan_draft_markdown = markdown
    if not (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip() and path:
        try:
            from pathlib import Path

            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            logger.debug("[PlanModeReview] could not reload plan artifact %s", path, exc_info=True)
        else:
            ctx.scratch.plan_draft_markdown = text
            ctx.scratch.plan_draft_path = path


def _collect_plan_draft(ctx: LoopRuntimeContext) -> str:
    """Fallback: collect the last AI message from the step ledger.

    Used only when LLM synthesis is unavailable (no model configured).
    Returns the raw last AI text which may contain narration.
    """
    from soothe.sloop.utils.messages import last_ledger_ai_content

    report = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if report:
        return report
    return last_ledger_ai_content(ctx.loop_state).strip()


def _record_plan_completion_ledger(
    ctx: LoopRuntimeContext,
    plan_body: str,
) -> None:
    """Record the plan as a ``goal_completion`` Human–AI pair in the ledger.

    The Human message carries the goal text; the AI message carries the full
    plan body (not just the path). This replaces the intermediate
    ``execute_step`` messages as the canonical terminal report so subsequent
    goals see a clean plan-completion entry in the ledger projection.
    """
    if ctx.ce is None:
        logger.debug("[PlanModeReview] No CE; skipping goal_completion ledger pair")
        return
    from soothe.sloop.utils.messages import (
        LoopAIMessage,
        LoopHumanMessage,
        _record_ledger_message,
    )

    state = ctx.loop_state
    goal_text = resolve_user_request(state) or state.goal or "plan"
    iteration = getattr(state, "iteration", 0)
    thread_id = getattr(state, "thread_id", None)
    workspace = getattr(state, "workspace", None)

    human_msg = LoopHumanMessage(
        content=goal_text,
        thread_id=thread_id,
        iteration=iteration,
        goal_summary=(goal_text[:200] if goal_text else None),
        workspace=workspace,
        phase="goal_completion",
    )
    ai_msg = LoopAIMessage(
        content=plan_body,
        thread_id=thread_id,
        iteration=iteration,
        phase="goal_completion",
    )
    _record_ledger_message(ctx.ce, human_msg, "goal_completion")
    _record_ledger_message(ctx.ce, ai_msg, "goal_completion")
    logger.info(
        "[PlanModeReview] Recorded goal_completion ledger pair (plan chars=%d)",
        len(plan_body),
    )


def _record_plan_action_ledger(
    ctx: LoopRuntimeContext,
    action_text: str,
) -> None:
    """Record the user's plan review action as a new ``goal_completion`` AI message.

    Called on approve / reject / comment so the ledger has a terminal record
    of the user's decision. Subsequent goals (e.g. the implementation goal
    after approve) will see this in the ledger projection.
    """
    if ctx.ce is None:
        return
    from soothe.sloop.utils.messages import (
        LoopAIMessage,
        _record_ledger_message,
    )

    state = ctx.loop_state
    ai_msg = LoopAIMessage(
        content=action_text,
        thread_id=getattr(state, "thread_id", None),
        iteration=getattr(state, "iteration", 0),
        phase="goal_completion",
    )
    _record_ledger_message(ctx.ce, ai_msg, "goal_completion")
    logger.info(
        "[PlanModeReview] Recorded plan action in ledger: %s",
        action_text[:120],
    )


def handle_plan_mode_review_answer(
    ctx: LoopRuntimeContext,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Handle approve / reject / comment after plan-mode review.

    On approve: set ``LoopState.approved_plan_*`` so the DISPATCH grounding
    chain consumes it. Record the action in the ledger.
    """
    from soothe.sloop.clarification.protocol import answer_from_state

    hydrate_scratch_from_pending(ctx, state)
    raw_answer = state.get("pending_clarification_answer")
    try:
        answer = answer_from_state(raw_answer or {})
    except ValueError:
        logger.exception("[PlanModeReview] malformed plan-mode review answer")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "fatal",
        }

    action, comments = parse_plan_review_answers(answer.answers)
    path = getattr(ctx.scratch, "plan_draft_path", None)
    report = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()

    if action == "approve":
        if path:
            update_plan_artifact_status(path, "approved")
        body = strip_plan_frontmatter(report) if report else ""
        state_obj = ctx.loop_state
        if state_obj is not None:
            state_obj.approved_plan_path = str(path) if path else None
            state_obj.approved_plan_markdown = body or None
        ctx.scratch.plan_review_comments = None
        _record_plan_action_ledger(ctx, "Plan approved by operator.")
        logger.info("[PlanModeReview] Plan approved; grounding into DISPATCH")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
            "intent_route": None,
            "approved_plan_markdown": body or None,
            "approved_plan_path": str(path) if path else None,
        }

    if action == "reject":
        if path:
            update_plan_artifact_status(path, "rejected")
        ctx.scratch.plan_review_comments = None
        _record_plan_action_ledger(ctx, "Plan rejected by operator.")
        logger.info("[PlanModeReview] Plan rejected")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
        }

    # More comments → store feedback for the next plan-mode iteration.
    ctx.scratch.plan_review_comments = comments
    action_text = f"Plan revision requested: {comments}" if comments else "Plan revision requested."
    _record_plan_action_ledger(ctx, action_text)
    logger.info("[PlanModeReview] Plan needs revision; comments stored")
    return build_plan_mode_review_pending(ctx)


async def node_plan_review(ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
    """Plan review graph node: collect plan, write artifact, record completion, emit clarification.

    When ``interaction_mode == "plan"``, ``route_after_root_eval`` routes here
    instead of ``FINALIZE``. This node:

    1. Synthesizes a plan document from the step's execution evidence via an
       LLM call (``synthesize_plan``). This avoids extracting/truncating from
       raw step output which contains mixed narration + tool results.
    2. Writes the synthesized plan to ``.soothe/plans/`` via ``save_plan_draft``.
    3. Records a ``goal_completion`` Human–AI pair in the ledger with the full
       plan body as the AI message (so subsequent goals see a clean terminal
       report, not intermediate ``execute_step`` messages).
    4. Returns a pending clarification (``ORIGIN_PLAN_MODE_REVIEW``) so the
       graph routes to ``AWAIT_USER`` for the approve/reject/comment popup.

    On clarification resume (approve/reject/comment), ``route_after_clarification``
    routes back here; ``handle_plan_mode_review_answer`` processes the answer and
    records the user's action in the ledger.
    """
    # If this is a clarification-resume turn, handle the answer first.
    if state.get("pending_clarification_answer"):
        return handle_plan_mode_review_answer(ctx, state)

    # Fresh plan review: synthesize the plan from step execution evidence.
    # If a draft is already on scratch (e.g. from a prior comment iteration),
    # use it instead of making another LLM call.
    plan_draft = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if not plan_draft:
        # LLM-driven plan synthesis from execute_step ledger evidence.
        strange_loop = ctx.strange_loop
        synth_llm = strange_loop.goal_synthesis_model() or strange_loop._fast_llm
        if synth_llm is None:
            logger.warning("[PlanModeReview] No synthesis model available; using fallback")
            plan_draft = _collect_plan_draft(ctx)
        else:
            plan_draft = await synthesize_plan(ctx, llm=synth_llm, config=strange_loop.config)
        if not plan_draft:
            logger.warning("[PlanModeReview] Plan synthesis produced empty output; using fallback")
            plan_draft = _collect_plan_draft(ctx)

    path = save_plan_draft(ctx, plan_draft)
    if not path:
        logger.warning("[PlanModeReview] Failed to write plan artifact; ending goal")
        return {"last_outcome": "fatal"}

    # Record the plan as a goal_completion ledger pair (full plan body, not
    # just the path). This replaces intermediate execute_step messages as
    # the canonical terminal report for this goal.
    _record_plan_completion_ledger(ctx, plan_draft)

    # Emit the approve/reject/comment clarification.
    return build_plan_mode_review_pending(ctx)


__all__ = [
    "build_plan_mode_review_pending",
    "handle_plan_mode_review_answer",
    "hydrate_scratch_from_pending",
    "node_plan_review",
    "save_plan_draft",
]
