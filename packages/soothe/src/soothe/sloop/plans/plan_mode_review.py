"""Plan-mode review host module: approve / reject / refine for plan mode."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from soothe.sloop.clarification.origins import (
    ORIGIN_PLAN_MODE_REVIEW,
    PLAN_MODE_REVIEW_INTERRUPT_PREFIX,
)
from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
    request_to_state,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.plans.artifact import (
    parse_plan_review_answers,
    strip_empty_plan_sections,
    update_plan_artifact_status,
    write_plan_artifact,
)
from soothe.sloop.plans.plan_synthesizer import synthesize_plan
from soothe.sloop.state.schemas import PlanResult
from soothe.sloop.utils.goal_text import resolve_user_request
from soothe.sloop.utils.messages import last_ledger_ai_content

logger = logging.getLogger(__name__)

_PLAN_MODE_REVIEW_QUESTIONS: tuple[dict, ...] = (
    {
        "question": "Action for this plan: Approve, Refine, or Reject?",
        "header": "Plan review",
        "options": [
            {
                "label": "Approve",
                "description": "Accept the plan and proceed to implementation.",
            },
            {
                "label": "Refine",
                "description": "Request changes with refinement instructions.",
            },
            {
                "label": "Reject",
                "description": "Reject the plan and terminate this goal.",
            },
        ],
    },
)

# Matches the ``## Plan: <title>`` marker that the plan-mode addendum
# (``plan_mode_addendum.xml``) instructs the agent to emit as its final
# message. When present in the step's last AI message, the plan body can
# be extracted directly — no LLM synthesis call needed.
_PLAN_TITLE_RE = re.compile(r"(?m)^[ \t]*##[ \t]+Plan:[ \t]+\S")


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


def _extract_plan_from_step_result(ctx: LoopRuntimeContext) -> str:
    """Extract a plan document from the step's final AI message.

    The plan-mode addendum instructs the planning agent to output ONLY the
    final plan document (`## Plan: <title>`) as its last message. When the
    agent followed that instruction, the step's last non-planning ledger AI
    message already contains a complete, well-structured plan — no LLM
    synthesis call is needed.

    This returns the plan body (stripped) when the `## Plan:` marker is
    present, otherwise an empty string so the caller falls back to
    `synthesize_plan`.
    """
    try:
        content = last_ledger_ai_content(ctx.loop_state)
    except Exception:
        logger.debug("[PlanModeReview] step result extraction failed", exc_info=True)
        return ""
    content = (content or "").strip()
    if not content:
        return ""
    if not _PLAN_TITLE_RE.search(content):
        # Final AI message is not plan-shaped (narration / chitchat / error).
        # Let synthesis rebuild a plan from the execution evidence.
        logger.debug("[PlanModeReview] step result lacks '## Plan:' marker; will synthesize")
        return ""
    # Trim any leading preface before the plan title (agent occasionally emits
    # a short prose lead-in despite the addendum). Keep the title line onward.
    match = _PLAN_TITLE_RE.search(content)
    if match and match.start() > 0:
        content = content[match.start() :].strip()
    return content


def save_plan_draft(ctx: LoopRuntimeContext, report: str) -> str | None:
    """Write the plan draft to `.soothe/plans/` and store on scratch."""
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

    Persist `plan_path` / `plan_markdown` / `plan_review_comments` on the
    pending channel so a clarification-resume turn (fresh scratch) can still
    hydrate the plan body and any pending refinement comments after a worker
    crash/restart.
    """
    req = ClarificationRequest(
        questions=_PLAN_MODE_REVIEW_QUESTIONS,
        origin_node=ORIGIN_PLAN_MODE_REVIEW,
        origin_interrupt_id=(f"{PLAN_MODE_REVIEW_INTERRUPT_PREFIX}{uuid.uuid4().hex[:8]}"),
        loop_state=_build_loop_state_view(ctx),
    )
    pending = request_to_state(req)
    path = (getattr(ctx.scratch, "plan_draft_path", None) or "").strip()
    markdown = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    comments = (getattr(ctx.scratch, "plan_review_comments", None) or "").strip()
    if path:
        pending["plan_path"] = path
    if markdown:
        pending["plan_markdown"] = markdown
    if comments:
        pending["plan_review_comments"] = comments
    return {
        "pending_clarification": pending,
        "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
        "pending_clarification_answer": None,
    }


def hydrate_scratch_from_pending(ctx: LoopRuntimeContext, state: dict[str, Any]) -> None:
    """Restore plan draft and refinement comments onto scratch after a clarification-resume turn."""
    pending = state.get("pending_clarification")
    if not isinstance(pending, dict):
        return
    path = str(pending.get("plan_path") or "").strip()
    markdown = str(pending.get("plan_markdown") or "").strip()
    comments = str(pending.get("plan_review_comments") or "").strip()
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
    # Restore refinement comments so _refine_plan can re-run after a worker
    # crash/restart if the refinement synthesis was interrupted mid-flight.
    if comments and not (getattr(ctx.scratch, "plan_review_comments", None) or "").strip():
        ctx.scratch.plan_review_comments = comments


def _record_plan_completion_ledger(
    ctx: LoopRuntimeContext,
    plan_body: str,
) -> None:
    """Record the plan as a `goal_completion` Human–AI pair in the ledger.

    The Human message carries the goal text; the AI message carries the full
    plan body (not just the path). This replaces the intermediate
    `execute_step` messages as the canonical terminal report so subsequent
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
    """Record the user's plan review action as a new `goal_completion` AI message.

    Called on approve / reject / refine so the ledger has a record
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
    """Handle approve / reject / refine after plan-mode review.

    On approve: stash a follow-on exec signal on `ctx.scratch.follow_on_exec`
    and set `plan_approved_follow_on` so routers finalize the plan-mode goal
    (its root already completed during exploration). The daemon enqueues a
    fresh exec goal carrying the approved plan path. Record the action in the
    ledger.

    On reject: terminate the current goal outright — no follow-on goal, no plan
    result, no ledger action entry, and no completion report. `plan_rejected`
    on scratch tells the finalize node to skip completion work entirely.

    On refine: store the user's comments as `plan_review_comments` feedback
    and re-emit the plan review clarification so the goal stays in plan mode
    (`AWAIT_USER`) for further refinement.
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
        # Bug #3: do NOT ground the approved plan onto this goal's root — the
        # plan-mode root already executed and completed (with decompose_task
        # stripped), so grounding there would leave ready_steps() empty and
        # route to an Eval step instead of executing the plan. Instead, stash
        # a follow-on exec signal for the finalize node to attach to the
        # ``completed`` event; the daemon enqueues a fresh exec goal carrying
        # the approved plan path, which DISPATCH grounds onto its own fresh
        # root in agent mode (decompose_task available).
        goal_prompt = (
            resolve_user_request(ctx.loop_state)
            or ctx.loop_state.goal
            or "Execute the approved plan"
        )
        ctx.scratch.follow_on_exec = {
            "goal_prompt": goal_prompt,
            "plan_path": str(path) if path else None,
        }
        # Bug #4: ``route_after_plan_review`` routes approve → FINALIZE, and
        # ``node_goal_completion`` requires ``ctx.scratch.plan_result`` (it
        # fatally errors with "Goal completion reached without plan result" when
        # it is None). The plan-mode path skips DISPATCH, so the dispatch/agent
        # branches that normally set ``plan_result`` never ran. Build a terminal
        # PlanResult here so finalize proceeds, attaches ``follow_on_exec`` to
        # the ``completed`` event, and enqueues the exec goal. ``status="done"``
        # marks the plan-mode goal terminal and ``require_goal_completion=False``
        # selects the ``ledger_direct`` completion strategy — the plan body is
        # already in the ledger as a ``goal_completion`` AI message (recorded by
        # ``_record_plan_completion_ledger``), so no synthesis call is needed.
        plan_body = report or (
            "Plan approved by operator. Implementation will run in a follow-on goal."
        )
        ctx.scratch.plan_result = PlanResult(
            status="done",
            goal_progress="complete",
            assessment_reasoning="Plan-mode goal: plan approved by operator.",
            plan_action="new",
            decision=None,
            next_action=goal_prompt[:500],
            full_output=plan_body,
            evidence_summary=plan_body[:2048],
            require_goal_completion=False,
        )
        ctx.scratch.plan_review_comments = None
        _record_plan_action_ledger(ctx, "Plan approved by operator.")
        logger.info("[PlanModeReview] Plan approved; follow-on exec goal enqueues on finalize")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
            "intent_route": None,
            "plan_approved_follow_on": True,
        }

    if action == "reject":
        if path:
            update_plan_artifact_status(path, "rejected")
        # Reject ends the goal outright: no plan result, no goal-completion
        # ledger pair, no synthesis. The finalize node reads ``plan_rejected``
        # and terminates without producing a report the user did not ask for.
        ctx.scratch.plan_review_comments = None
        ctx.scratch.plan_rejected = True
        logger.info("[PlanModeReview] Plan rejected; terminating current goal without report")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_clarification_origin": None,
            "intent_route": None,
            "plan_rejected_terminal": True,
        }

    if action == "refine":
        # Store the user's comments as refinement feedback for the next
        # plan-mode iteration, then re-emit the review so the goal stays in
        # plan mode (AWAIT_USER).
        ctx.scratch.plan_review_comments = comments
        action_text = (
            f"Plan refinement requested: {comments}" if comments else "Plan refinement requested."
        )
        _record_plan_action_ledger(ctx, action_text)
        logger.info("[PlanModeReview] Plan refinement requested; re-emitting review")
        out = build_plan_mode_review_pending(ctx)
        # Signal ``node_plan_review`` that a refinement re-synthesis is
        # needed. ``handle_plan_mode_review_answer`` is sync, so it cannot
        # run the async LLM synthesis itself; the node (async) consumes
        # ``ctx.scratch.plan_review_comments`` and performs the re-synthesis
        # after this function returns, then overwrites the draft.
        if (comments or "").strip():
            out["plan_refinement_requested"] = True
        return out


async def _refine_plan(ctx: LoopRuntimeContext) -> str:
    """Run a refinement re-synthesis using the operator's comments.

    Reads `ctx.scratch.plan_review_comments` and the current draft, calls
    `synthesize_plan` with both so the LLM revises the plan to address the
    feedback. Returns the revised plan text (empty on failure). Does NOT
    clear `plan_review_comments` — the caller owns lifecycle so the
    comments survive a synthesis failure for the next attempt.
    """
    comments = (getattr(ctx.scratch, "plan_review_comments", None) or "").strip()
    prior = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if not comments or not prior:
        return ""
    strange_loop = ctx.strange_loop
    synth_llm = strange_loop.goal_synthesis_model() or strange_loop._fast_llm
    if synth_llm is None:
        logger.warning("[PlanModeReview] No synthesis model for refinement")
        return ""
    return await synthesize_plan(
        ctx,
        llm=synth_llm,
        config=strange_loop.config,
        refinement_comments=comments,
        prior_plan=prior,
    )


async def node_plan_review(ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
    """Plan review graph node: collect plan, write artifact, record completion, emit clarification.

    When `interaction_mode == "plan"`, `route_after_root_eval` routes here
    instead of `FINALIZE`. This node:

    1. Extracts the plan document from the step's final AI message (the
       plan-mode addendum instructs the agent to output `## Plan: <title>`
       as its last message). When the agent followed that instruction, no LLM
       call is needed — the step result already IS the plan. This mirrors the
       `LEDGER_DIRECT` completion strategy and avoids a synthesis call.
    2. Falls back to LLM synthesis (`synthesize_plan`) only when extraction
       fails — e.g. the final message lacks the `## Plan:` marker (agent
       narrated instead of producing a plan, or an error truncated output).
    3. Writes the plan to `.soothe/plans/` via `save_plan_draft`.
    4. Records a `goal_completion` Human–AI pair in the ledger with the full
       plan body as the AI message (so subsequent goals see a clean terminal
       report, not intermediate `execute_step` messages).
    5. Returns a pending clarification (`ORIGIN_PLAN_MODE_REVIEW`) so the
       graph routes to `AWAIT_USER` for the approve/reject/refine popup.

    On clarification resume (approve/reject/refine), `route_after_clarification`
    routes back here; `handle_plan_mode_review_answer` processes the answer and
    records the user's action in the ledger. On Refine with comments,
    the node runs an async refinement re-synthesis (`synthesize_plan` with the
    comments + prior plan) so the user sees a *revised* plan, not the same draft.
    """
    # If this is a clarification-resume turn, handle the answer first.
    if state.get("pending_clarification_answer"):
        out = handle_plan_mode_review_answer(ctx, state)
        # Refine with comments: re-synthesize the plan with the user's
        # feedback before re-emitting the review. ``handle_plan_mode_review_answer``
        # is sync (it stored the comments on scratch + flagged the return);
        # the async synthesis happens here.
        if out.get("plan_refinement_requested"):
            comments = (getattr(ctx.scratch, "plan_review_comments", None) or "").strip()
            await ctx.emit(
                "plan_refinement_started",
                {"comments": comments[:200] if comments else ""},
            )
            refined = await _refine_plan(ctx)
            if refined:
                # Overwrite the draft + artifact; the pending payload built by
                # ``handle_plan_mode_review_answer`` still references the *old*
                # draft, so rebuild it from the revised plan.
                path = save_plan_draft(ctx, refined)
                if path:
                    _record_plan_completion_ledger(ctx, refined)
                    out = build_plan_mode_review_pending(ctx)
                ctx.scratch.plan_review_comments = None
                await ctx.emit("plan_refinement_completed", {"plan_chars": len(refined)})
            else:
                # Synthesis failed — keep the old draft pending and clear the
                # stale comments so a subsequent approve does not re-trigger.
                logger.warning(
                    "[PlanModeReview] Refinement synthesis failed; re-emitting prior draft"
                )
                ctx.scratch.plan_review_comments = None
                await ctx.emit("plan_refinement_failed", {})
        return out

    # Fresh plan review: prefer extracting the plan from the step's final AI
    # message (the plan-mode addendum tells the agent to output the plan as its
    # last message). Only fall back to LLM synthesis when extraction fails —
    # this skips a full synthesis call + its input-token cost in the common
    # case where the agent already produced a plan-shaped final message.
    # If a draft is already on scratch (e.g. from a prior comment iteration),
    # use it instead of re-extracting or synthesizing.
    plan_draft = (getattr(ctx.scratch, "plan_draft_markdown", None) or "").strip()
    if not plan_draft:
        plan_draft = _extract_plan_from_step_result(ctx)

    if not plan_draft:
        # Extraction failed: fall back to LLM-driven plan synthesis from
        # execute_step ledger evidence.
        strange_loop = ctx.strange_loop
        synth_llm = strange_loop.goal_synthesis_model() or strange_loop._fast_llm
        if synth_llm is None:
            logger.warning("[PlanModeReview] No synthesis model available")
            plan_draft = ""
        else:
            await ctx.emit("plan_synthesis_started", {})
            plan_draft = await synthesize_plan(ctx, llm=synth_llm, config=strange_loop.config)
            await ctx.emit(
                "plan_synthesis_completed",
                {"plan_chars": len(plan_draft)},
            )

    if not plan_draft:
        # Synthesis failed (rate limit, error, no model). Do NOT fall back to
        # raw step output — it contains narration/tool results, not a plan.
        # Emit a placeholder so the user can comment to retry.
        plan_draft = (
            "## Plan: Synthesis Failed\n\n"
            "### Goal\n"
            f"{resolve_user_request(ctx.loop_state) or ctx.loop_state.goal or 'unknown'}\n\n"
            "### Solution\n"
            "Plan synthesis from step evidence failed (rate limit or LLM error). "
            "The step execution evidence is available in the ledger.\n\n"
            "### Changes\n"
            "1. **Retry plan synthesis**\n"
            "   - Select 'Refine' below and type 'retry' to regenerate the plan.\n"
        )
        logger.warning("[PlanModeReview] Plan synthesis failed; emitting placeholder")

    # Strip sections whose body is a bare ``None`` / ``N/A`` placeholder.
    # The templates instruct the LLM to omit inapplicable sections, but models
    # sometimes emit a literal ``None`` instead. This keeps the plan compact.
    plan_draft = strip_empty_plan_sections(plan_draft)

    path = save_plan_draft(ctx, plan_draft)
    if not path:
        logger.warning("[PlanModeReview] Failed to write plan artifact; ending goal")
        return {"last_outcome": "fatal"}

    # Record the plan as a goal_completion ledger pair (full plan body, not
    # just the path). This replaces intermediate execute_step messages as
    # the canonical terminal report for this goal.
    _record_plan_completion_ledger(ctx, plan_draft)

    # Emit the approve/reject/refine clarification.
    return build_plan_mode_review_pending(ctx)


__all__ = [
    "build_plan_mode_review_pending",
    "handle_plan_mode_review_answer",
    "hydrate_scratch_from_pending",
    "node_plan_review",
    "save_plan_draft",
]
