"""Loop-continuation context for execute envelopes and plan prompts.

When ``continue_loop`` is set, the prior goal's synthesized ``goal_completion``
report (RFC-225) is the authoritative source for what to do next — not a replay of
prior ``execute_step`` ledger rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint
    from soothe.foundation.sloop.state.schemas import LoopState

PRIOR_GOAL_COMPLETION_MAX_CHARS = 12_000
CONTINUATION_ASSESS_REASONING_MAX_CHARS = 240

_CONTINUE_KEYWORD_DESCRIPTION = "Continue prior goal completion recommendations"
_CONTINUE_KEYWORD_FULL_DESCRIPTION = (
    "Advance the loop by executing the recommended next actions from the prior goal's "
    "completion report (PRIOR GOAL COMPLETION in this message). Prioritize concrete "
    "follow-up work — implementation, fixes, tests, or deliverables named in that report. "
    "Do not repeat discovery, reading, RFC review, trace analysis, or other work already "
    "finished in the prior goal; treat the completion report as authoritative context."
)


@dataclass(frozen=True, slots=True)
class ContinueBootstrapStepBriefs:
    """Short TUI label and standalone execute brief for loop-continuation bootstrap."""

    description: str
    full_description: str


def _truncate_description(text: str, *, max_words: int = 16) -> str:
    """Fit a user-facing step summary under the StepAction description budget."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def build_continue_bootstrap_step_briefs(*, user_goal: str) -> ContinueBootstrapStepBriefs:
    """Build description + full_description for loop-continuation bootstrap steps.

    Mirrors plan-generate: ``description`` is a short TUI/logging label;
    ``full_description`` is the standalone execution brief the executor sends as GOAL.
    """
    goal = (user_goal or "").strip()
    if is_continue_keyword(goal):
        return ContinueBootstrapStepBriefs(
            description=_CONTINUE_KEYWORD_DESCRIPTION,
            full_description=_CONTINUE_KEYWORD_FULL_DESCRIPTION,
        )

    description = _truncate_description(goal)
    full_description = (
        f"Address the follow-up request: {goal}. "
        "Use the prior goal's completion report (PRIOR GOAL COMPLETION) as authoritative "
        "background. Do not re-run prior goal execute steps or redo finished analysis; "
        "build on what was already concluded and produce concrete output for this request."
    )
    return ContinueBootstrapStepBriefs(
        description=description,
        full_description=full_description,
    )


def build_continue_bootstrap_step_description(*, user_goal: str) -> str:
    """Return the bootstrap execute brief (``full_description``) for legacy callers."""
    return build_continue_bootstrap_step_briefs(user_goal=user_goal).full_description


def _message_phase(msg: Any) -> str | None:
    phase = getattr(msg, "phase", None)
    return phase if isinstance(phase, str) else None


def ledger_goal_completion_text(loop_messages: list[Any]) -> str:
    """Return the latest ``goal_completion`` AI body from the orchestration ledger."""
    content = ""
    for msg in loop_messages:
        if _message_phase(msg) != "goal_completion":
            continue
        msg_type = type(msg).__name__
        if msg_type.endswith("AIMessage") or msg_type == "LoopAIMessage":
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                content = text
    return content


def checkpoint_completions_by_goal_text(
    checkpoint: StrangeLoopCheckpoint | None,
    *,
    exclude_goal_id: str | None = None,
) -> dict[str, str]:
    """Map prior goal text → persisted ``goal_completion`` from checkpoint."""
    out: dict[str, str] = {}
    if checkpoint is None:
        return out
    for rec in checkpoint.goal_history:
        if exclude_goal_id and rec.goal_id == exclude_goal_id:
            continue
        goal_text = (rec.goal_text or "").strip()
        completion = (rec.goal_completion or "").strip()
        if goal_text and completion:
            out[goal_text] = completion
    return out


def resolve_prior_goal_completion(
    *,
    loop_messages: list[Any],
    checkpoint: StrangeLoopCheckpoint | None = None,
    prior_goal_text: str | None = None,
    exclude_goal_id: str | None = None,
) -> str:
    """Resolve the best prior-goal completion body for continuation grounding."""
    by_text = checkpoint_completions_by_goal_text(checkpoint, exclude_goal_id=exclude_goal_id)
    if prior_goal_text:
        matched = by_text.get(prior_goal_text.strip())
        if matched:
            return matched
    if by_text:
        # Most recent completed prior goal in checkpoint order.
        for rec in reversed(checkpoint.goal_history if checkpoint else []):
            if exclude_goal_id and rec.goal_id == exclude_goal_id:
                continue
            text = (rec.goal_text or "").strip()
            completion = (rec.goal_completion or "").strip()
            if text and completion:
                return completion
    return ledger_goal_completion_text(loop_messages)


def build_prior_goal_completion_block(
    loop_messages: list[Any],
    *,
    checkpoint: StrangeLoopCheckpoint | None = None,
    prior_goal_text: str | None = None,
    exclude_goal_id: str | None = None,
    max_chars: int = PRIOR_GOAL_COMPLETION_MAX_CHARS,
) -> str:
    """Build capped PRIOR GOAL COMPLETION text for execute/plan prompts."""
    body = resolve_prior_goal_completion(
        loop_messages=loop_messages,
        checkpoint=checkpoint,
        prior_goal_text=prior_goal_text,
        exclude_goal_id=exclude_goal_id,
    ).strip()
    if not body:
        return ""
    if max_chars <= 0 or len(body) <= max_chars:
        return body
    return body[: max_chars - 1].rstrip() + "…"


def format_prior_goal_completion_section(body: str) -> str:
    """Render PRIOR GOAL COMPLETION section (same label as plan-generate / execute)."""
    text = (body or "").strip()
    if not text:
        return ""
    return f"PRIOR GOAL COMPLETION:\n{text}"


def polish_continuation_assess_reasoning(
    reasoning: str,
    *,
    max_chars: int = CONTINUATION_ASSESS_REASONING_MAX_CHARS,
) -> str:
    """Normalize continuation-assess reasoning for TUI cards and logs."""
    text = " ".join((reasoning or "").split())
    if not text:
        return ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 1].rstrip(".,;:")
    return clipped + "…"


def is_continuation_first_plan(state: LoopState) -> bool:
    """True for iter=0 continuation goals before any in-goal execution."""
    return (
        bool(getattr(state, "continue_loop", False))
        and state.iteration == 0
        and not state.step_results
    )


def build_prior_goal_summaries(
    *,
    ce: Any | None,
    checkpoint: StrangeLoopCheckpoint | None,
    exclude_goal_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compact summary of prior goals for continuation-assess and plan-generate.

    Reads goal metadata from the CE GoalStepDAG and completion bodies from
    checkpoint ``goal_completion`` fields (same resolution order as
    ``resolve_prior_goal_completion``).

    Args:
        ce: ContextEngine (or compatible) exposing ``get_all_goals()``.
        checkpoint: StrangeLoop checkpoint with persisted goal completions.
        exclude_goal_id: Current goal id to omit from the summary list.

    Returns:
        List of dicts with keys ``goal_id``, ``goal_text``, ``completion``,
        ``step_count``.
    """
    completions_by_text = checkpoint_completions_by_goal_text(
        checkpoint,
        exclude_goal_id=exclude_goal_id,
    )
    if ce is None:
        return []
    out: list[dict[str, Any]] = []
    for goal in ce.get_all_goals():
        if exclude_goal_id and goal.id == exclude_goal_id:
            continue
        if goal.status not in ("completed", "cancelled", "failed", "active"):
            continue
        completed_steps = [s for s in goal.steps.nodes.values() if s.status == "completed"]
        goal_text = (goal.description or "").strip()
        completion = completions_by_text.get(goal_text, "")
        if not completion and goal.action_history:
            completion = goal.action_history[-1]
        out.append(
            {
                "goal_id": goal.id,
                "goal_text": goal.description,
                "completion": completion,
                "step_count": len(completed_steps),
            }
        )
    return out


def build_continuation_plan_prior_goal_completion(
    *,
    loop_messages: list[Any],
    checkpoint: StrangeLoopCheckpoint | None = None,
    exclude_goal_id: str | None = None,
    max_chars: int = 0,
) -> str:
    """Build full PRIOR GOAL COMPLETION text for continuation plan prompts."""
    return build_prior_goal_completion_block(
        loop_messages,
        checkpoint=checkpoint,
        exclude_goal_id=exclude_goal_id,
        max_chars=max_chars,
    )


def build_continuation_execution_hints(*, has_prior_goal_completion: bool) -> str:
    """Build EXECUTION HINTS for a loop-continuation bootstrap step."""
    instruction_lines = [
        "- Execute the step described in GOAL above",
        "- Produce output matching the expected output specification",
    ]
    if has_prior_goal_completion:
        instruction_lines.insert(
            0,
            "- PRIOR GOAL COMPLETION is authoritative; do not repeat prior goal execute steps",
        )
        instruction_lines.insert(
            1,
            "- Implement or advance the recommended next actions from that report",
        )
    return "Instructions:\n" + "\n".join(instruction_lines)


__all__ = [
    "PRIOR_GOAL_COMPLETION_MAX_CHARS",
    "CONTINUATION_ASSESS_REASONING_MAX_CHARS",
    "ContinueBootstrapStepBriefs",
    "build_continue_bootstrap_step_briefs",
    "build_continue_bootstrap_step_description",
    "build_continuation_execution_hints",
    "build_continuation_plan_prior_goal_completion",
    "build_prior_goal_completion_block",
    "build_prior_goal_summaries",
    "checkpoint_completions_by_goal_text",
    "format_prior_goal_completion_section",
    "is_continuation_first_plan",
    "ledger_goal_completion_text",
    "polish_continuation_assess_reasoning",
    "resolve_prior_goal_completion",
]
