"""Report-commit consensus judge prompt assembly."""

from __future__ import annotations

from soothe_autopilot.prompts.fragments import CONSENSUS_JUDGE_INSTRUCTIONS
from soothe_autopilot.prompts.roles import CONSENSUS_JUDGE_OPENER

__all__ = ["build_consensus_prompt"]


def build_consensus_prompt(
    goal: str,
    response: str,
    *,
    dag_context: str = "",
) -> str:
    """Build prompt for structured report-commit judgment.

    Pass the full CE Goal Report projection into the judge prompt. Do not clip
    with preview truncation here — truncation caused false `fail` when the
    model mistook the preview for incomplete work.

    Args:
        goal: Original goal description.
        response: Full CE Goal Report projection text.
        dag_context: Optional compact CE DAG slice for bounded ops.

    Returns:
        Assembled human-message prompt (opener + envelope + instructions).
    """
    parts = [
        CONSENSUS_JUDGE_OPENER,
        f"\nGoal: {goal}",
        f"\nGoal Report (from ContextEngine):\n{response}",
    ]
    if dag_context.strip():
        parts.append(f"\n{dag_context.strip()}")
    parts.append(f"\n{CONSENSUS_JUDGE_INSTRUCTIONS}")
    return "\n".join(parts)
