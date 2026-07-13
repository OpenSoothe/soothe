"""Interrupted-goal ledger marker (RFC-214 ledger phase ``goal_interrupted``).

When a goal is terminated mid-Execute **without** reaching the
``goal_completion`` success node — i.e. user cancel / new query superseding an
in-flight goal, max-iterations exhausted, fatal execute error, or consecutive
rate-limit circuit break — no ``phase="goal_completion"`` ledger pair is
written. Downstream projection (``plan_ledger_projection``) keys segment
boundaries off the ``goal_completion`` AI marker, so without a marker the
interrupted goal's partial ``execute_step`` rows bleed into the next goal's
"current segment" and the planner cannot tell where the interrupted goal ended
and the new one began.

This module writes a deterministic ``phase="goal_interrupted"`` Human+AI pair
at every non-success terminal path. The AI body is a compact digest of what was
done / what's left, sourced from ``LoopState.prior_progress`` plus a last-AI
scan over the goal's ``execute_step`` rows — **no LLM call**, so the interrupt
path stays fast and failure-proof. The marker is a *phase tag*, not a goal
status; callers keep setting the existing ``cancelled`` / ``failed`` terminal
statuses (the cause discriminator) and this writer only adds the ledger marker
so projection can bound the segment and surface partial work to the next goal's
planning pass.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    _record_ledger_message,
)

if TYPE_CHECKING:
    from ..orchestrator.runtime_context import LoopRuntimeContext
    from ..state.schemas import LoopState

logger = logging.getLogger(__name__)

# Hard caps on the digest body so the marker stays cheap to project.
_MAX_STEP_SUMMARY_ROWS = 6
_MAX_EXCERPT_CHARS = 240
_MAX_EVIDENCE_EXCERPTS = 3
_MAX_DIGEST_CHARS = 1200

# Short human envelope naming the interrupt cause. Projection rewrites this
# label (see ``_compact_goal_interrupted_unit_for_projection``), so the exact
# wording only matters for raw ledger inspection / TUI badges.
_INTERRUPTED_LEDGER_HUMAN_BASE = "Goal interrupted before completion. Partial-work digest follows."


def _format_step_summary_lines(prior_progress: Any) -> list[str]:
    """Render the most recent wave's per-step rows as compact bullet lines."""
    summaries = getattr(prior_progress, "step_summaries", None) or []
    if not summaries:
        return []
    lines: list[str] = []
    for row in summaries[:_MAX_STEP_SUMMARY_ROWS]:
        sid = str(getattr(row, "step_id", "?") or "?").strip()[:64]
        status = str(getattr(row, "status", "unknown") or "unknown").strip()
        desc = str(getattr(row, "description", "") or "").strip()
        preview = str(getattr(row, "outcome_preview", "") or "").strip()
        head = desc if desc else sid
        head = head if len(head) <= 100 else head[:100] + "…"
        if preview and status != "completed":
            head = f"{head} — {preview}" if len(head) + len(preview) <= 160 else head
        lines.append(f"- [{status}] {head}")
    return lines


def _collect_execute_evidence_excerpts(state: LoopState) -> list[str]:
    """Return up to N short AI-text excerpts from the goal's execute_step rows.

    Walks ``state.loop_messages`` backward collecting ``execute_step`` AI body
    text (the user-facing synthesis of each wave), deduped by a 64-char prefix
    so repeated narration does not crowd the digest.
    """
    from soothe.foundation.sloop.utils.stream_normalize import (
        extract_text_from_message_content,
    )

    excerpts: list[str] = []
    seen_prefixes: set[str] = set()
    for msg in reversed(state.loop_messages):
        if len(excerpts) >= _MAX_EVIDENCE_EXCERPTS:
            break
        if getattr(msg, "phase", None) != "execute_step":
            continue
        if type(msg).__name__ not in ("LoopAIMessage", "AIMessage"):
            continue
        text = extract_text_from_message_content(getattr(msg, "content", None)).strip()
        if not text:
            continue
        prefix = text[:64]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        excerpts.append(text[:_MAX_EXCERPT_CHARS])
    excerpts.reverse()
    return excerpts


def _build_interrupted_digest(
    state: LoopState,
    *,
    reason: str,
    detail: str,
) -> str:
    """Build the ``goal_interrupted`` AI body (what was done / what's left).

    Deterministic, no LLM. Returns empty string when the goal produced no
    usable execute evidence — callers treat that as "no marker" (matching the
    ``goal_completion`` guard at ``goal_completion.py:102``).
    """
    prior_progress = getattr(state, "prior_progress", None)
    step_lines = _format_step_summary_lines(prior_progress) if prior_progress else []
    evidence = _collect_execute_evidence_excerpts(state)

    if not step_lines and not evidence:
        return ""

    parts: list[str] = []
    goal_text = (state.goal or "").strip()
    header = f"Goal interrupted ({reason})."
    if detail:
        header = f"{header} {detail.strip()}"
    if goal_text:
        header = f"{header}\nGoal: {goal_text[:200]}"
    parts.append(header)

    if step_lines:
        parts.append("Most recent wave steps:\n" + "\n".join(step_lines))

    if evidence:
        parts.append("Evidence produced (oldest first):\n" + "\n\n".join(evidence))

    parts.append(
        "Remaining: the new request should resume from the last completed step; "
        "do not redo work whose evidence appears above."
    )
    digest = "\n\n".join(parts)
    if len(digest) > _MAX_DIGEST_CHARS:
        digest = digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"
    return digest


async def append_goal_interrupted_ledger_pair(
    ctx: LoopRuntimeContext,
    *,
    reason: str,
    detail: str = "",
) -> None:
    """Append a ``phase="goal_interrupted"`` Human+AI ledger pair for the goal.

    Mirrors ``goal_completion._append_goal_completion_ledger_pair``. Writes a
    deterministic digest of the goal's partial execute work so the next goal's
    planning projection can bound the interrupted segment and surface what was
    done / what's left. Does **not** set goal status — the caller's terminal
    path already sets ``cancelled`` / ``failed`` (the cause discriminator).

    Args:
        ctx: Loop runtime context (carries ``ce``, ``ce_goal_id``, ``loop_state``).
        reason: Short interrupt-cause slug (``"user_cancelled"``,
            ``"max_iterations"``, ``"fatal_error"``, ``"rate_limited"``).
        detail: Optional extra context (e.g. the fatal error message).
    """
    state = ctx.loop_state
    ce = getattr(ctx, "ce", None)
    digest = _build_interrupted_digest(state, reason=reason, detail=detail)
    if not digest:
        logger.debug(
            "goal_interrupted marker skipped (no execute evidence) loop=%s goal=%s reason=%s",
            getattr(state, "thread_id", None),
            getattr(ctx, "ce_goal_id", None),
            reason,
        )
        return

    iteration_completed = int(state.iteration or 0)
    human_msg = LoopHumanMessage(
        content=_INTERRUPTED_LEDGER_HUMAN_BASE,
        thread_id=state.thread_id,
        iteration=iteration_completed,
        goal_summary=(state.goal[:200] if state.goal else None),
        workspace=state.workspace,
        phase="goal_interrupted",
    )
    ai_msg = LoopAIMessage(
        content=digest,
        thread_id=state.thread_id,
        iteration=iteration_completed,
        phase="goal_interrupted",
    )
    _record_ledger_message(ce, human_msg, "goal_interrupted")
    _record_ledger_message(ce, ai_msg, "goal_interrupted")

    # Make the digest available to continuation-assess's action_history fallback
    # (continuation_context.build_prior_goal_summaries reads action_history[-1]).
    ce_goal_id = getattr(ctx, "ce_goal_id", None)
    if ce is not None and ce_goal_id:
        try:
            ce.record_action(ce_goal_id, digest)
        except Exception:  # noqa: BLE001 - best-effort; marker already in ledger
            logger.debug(
                "record_action failed for goal_interrupted marker loop=%s goal=%s",
                state.thread_id,
                ce_goal_id,
                exc_info=True,
            )

    logger.info(
        "goal_interrupted marker written loop=%s goal=%s reason=%s digest_chars=%d",
        state.thread_id,
        ce_goal_id,
        reason,
        len(digest),
    )


__all__ = [
    "append_goal_interrupted_ledger_pair",
]
