"""Plan-mode review host module: approve / reject / comment for plan mode.

When ``interaction_mode == "plan"`` and a plan draft is ready, this module
builds a clarification request (origin ``ORIGIN_PLAN_MODE_REVIEW``) that
pauses execution for user input on critical design points.

On approve:
    - Write/update the plan markdown to ``.soothe/plans/`` via ``write_plan_artifact``.
    - Set ``LoopState.approved_plan_markdown`` + ``LoopState.approved_plan_path``
      so the existing DISPATCH grounding chain
      (``dispatch._ground_root_with_approved_plan`` → ``grounding.compose_root_full_description``
      → ``consume_approved_plan_from_state``) picks it up and grounds it into
      the root THREAD description, then clears it one-shot.
    - Routing to DISPATCH is handled by ``route_after_clarification`` checking
      ``LoopState.approved_plan_markdown`` non-empty — no scratch flag needed.

On reject:
    - Re-enter plan mode with prior context preserved.

On comment:
    - Incorporate feedback into ``plan_review_comments`` and regenerate.
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
    parse_planner_subagent_review_answers,
    strip_plan_frontmatter,
    update_plan_artifact_status,
    write_plan_artifact,
)
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


def handle_plan_mode_review_answer(
    ctx: LoopRuntimeContext,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Handle approve / reject / comment after plan-mode review.

    On approve: set ``LoopState.approved_plan_*`` so the DISPATCH grounding
    chain consumes it. No scratch handoff flag — routing reads
    ``approved_plan_markdown`` non-empty.
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

    action, comments = parse_planner_subagent_review_answers(answer.answers)
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
        logger.info("[PlanModeReview] Plan rejected")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
        }

    # More comments → store feedback for the next plan-mode iteration.
    ctx.scratch.plan_review_comments = comments
    logger.info("[PlanModeReview] Plan needs revision; comments stored")
    return build_plan_mode_review_pending(ctx)


def _collect_plan_draft(ctx: LoopRuntimeContext) -> str:
    """Collect the agent's final output from the ledger as the plan draft."""
    from soothe.sloop.utils.messages import last_ledger_ai_content

    report = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if report:
        return report
    # Fallback: last AI message from the ledger.
    return last_ledger_ai_content(ctx.loop_state).strip()


async def node_plan_review(ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
    """Plan review graph node: collect plan draft, write artifact, emit clarification.

    When ``interaction_mode == "plan"``, ``route_after_root_eval`` routes here
    instead of ``FINALIZE``. This node:

    1. Collects the agent's final output from the ledger as the plan draft.
    2. Writes the plan draft to ``.soothe/plans/`` via ``save_plan_draft``.
    3. Records a ledger pair (goal + plan_path, not full plan content) so the
       ledger shows what the goal was and where the plan was saved.
    4. Returns a pending clarification (``ORIGIN_PLAN_MODE_REVIEW``) so the
       graph routes to ``AWAIT_USER`` for the approve/reject/comment popup.

    On clarification resume (approve/reject/comment), ``route_after_clarification``
    routes back here; ``handle_plan_mode_review_answer`` processes the answer.
    """
    # If this is a clarification-resume turn, handle the answer first.
    if state.get("pending_clarification_answer"):
        return handle_plan_mode_review_answer(ctx, state)

    # Fresh plan review: collect the plan draft and write it.
    plan_draft = _collect_plan_draft(ctx)
    if not plan_draft:
        logger.warning("[PlanModeReview] No plan draft found; ending goal")
        return {"last_outcome": "fatal"}

    path = save_plan_draft(ctx, plan_draft)
    if not path:
        logger.warning("[PlanModeReview] Failed to write plan artifact; ending goal")
        return {"last_outcome": "fatal"}

    # Record ledger pair: goal + plan_path (not full plan content).
    if ctx.ce is not None:
        from soothe.sloop.utils.messages import (
            LoopAIMessage,
            LoopHumanMessage,
            _record_ledger_message,
        )

        goal_text = resolve_user_request(ctx.loop_state) or ctx.loop_state.goal or "plan"
        human_msg = LoopHumanMessage(
            content=goal_text,
            thread_id=getattr(ctx.loop_state, "thread_id", None),
            iteration=getattr(ctx.loop_state, "iteration", 0),
            goal_summary=(goal_text[:200] if goal_text else None),
            workspace=getattr(ctx.loop_state, "workspace", None),
            phase="execute_step",
            step_id="PLAN-DRAFT",
        )
        ai_msg = LoopAIMessage(
            content=f"Plan draft saved to: `{path}`",
            thread_id=getattr(ctx.loop_state, "thread_id", None),
            iteration=getattr(ctx.loop_state, "iteration", 0),
            phase="execute_step",
            step_id="PLAN-DRAFT",
        )
        _record_ledger_message(ctx.ce, human_msg, "execute_step")
        _record_ledger_message(ctx.ce, ai_msg, "execute_step")
    else:
        logger.debug("[PlanModeReview] No CE; skipping ledger pair for plan draft")

    # Emit the approve/reject/comment clarification.
    return build_plan_mode_review_pending(ctx)


__all__ = [
    "build_plan_mode_review_pending",
    "handle_plan_mode_review_answer",
    "hydrate_scratch_from_pending",
    "node_plan_review",
    "save_plan_draft",
]
