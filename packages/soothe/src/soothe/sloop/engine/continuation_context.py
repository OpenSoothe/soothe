"""Loop-continuation context for execute envelopes and plan prompts.

When ``continue_loop`` is set, each prior goal's canonical ``goal_completion``
ledger pair is the authoritative outcome document. Downstream prompts project those
native Human/AI turns (execute Slice A, planner ``new_goal`` ledger) instead of
replaying ``execute_step`` rows or pasting inline completion prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.sloop.engine.step_predecessor_context import ExecuteStepEnvelopeBody
from soothe.sloop.utils.continue_keyword import is_continue_keyword

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import LoopState

CONTINUATION_ASSESS_REASONING_MAX_CHARS = 240

_CONTINUE_KEYWORD_DESCRIPTION = "Continue prior goal completion recommendations"
_CONTINUE_KEYWORD_FULL_DESCRIPTION = (
    "Advance the loop by executing the recommended next actions from the prior goal's "
    "completion report in the projected ledger. Prioritize concrete follow-up work — "
    "implementation, fixes, tests, or deliverables named in that report. Do not repeat "
    "discovery, reading, RFC review, trace analysis, or other work already finished in "
    "the prior goal; treat the completion report as authoritative context."
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


def build_continue_bootstrap_step_briefs(
    *,
    user_goal: str,
) -> ContinueBootstrapStepBriefs:
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
        "Use the prior goal's projected completion report as authoritative background. "
        "Do not re-run prior goal execute steps or redo finished analysis; "
        "build on what was already concluded and produce concrete output for this request."
    )
    return ContinueBootstrapStepBriefs(
        description=description,
        full_description=full_description,
    )


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
    checkpoint: Any | None,
    exclude_goal_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compact summary of prior goals for continuation-assess and plan-generate.

    Reads goal metadata from the CE GoalStepDAG. Completion bodies come from
    CE ``action_history`` when present; full reports live in the ledger.

    Args:
        ce: ContextEngine (or compatible) exposing ``get_all_goals()``.
        checkpoint: StrangeLoop checkpoint with persisted goal completions.
        exclude_goal_id: Current goal id to omit from the summary list.

    Returns:
        List of dicts with keys ``goal_id``, ``goal_text``, ``completion``,
        ``step_count``.
    """
    _ = checkpoint
    completions_by_text: dict[str, str] = {}
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


def build_continuation_execution_hints(
    *, has_prior_goal_completion: bool
) -> ExecuteStepEnvelopeBody:
    """Build INSTRUCTIONS body for a loop-continuation bootstrap step."""
    instruction_lines = [
        "- Execute the step described in EXECUTION TASK above",
        "- Produce output matching the expected output specification",
    ]
    if has_prior_goal_completion:
        instruction_lines.insert(
            0,
            "- The projected prior goal completion report is authoritative; "
            "do not repeat prior goal execute steps",
        )
        instruction_lines.insert(
            1,
            "- Implement or advance the recommended next actions from that report",
        )
    return ExecuteStepEnvelopeBody(instructions="\n".join(instruction_lines))


__all__ = [
    "CONTINUATION_ASSESS_REASONING_MAX_CHARS",
    "ContinueBootstrapStepBriefs",
    "build_continue_bootstrap_step_briefs",
    "build_continuation_execution_hints",
    "build_prior_goal_summaries",
    "is_continuation_first_plan",
    "ledger_goal_completion_text",
    "polish_continuation_assess_reasoning",
]
