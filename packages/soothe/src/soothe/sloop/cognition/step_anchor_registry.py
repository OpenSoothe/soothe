"""Build STEP ANCHOR REGISTRY text for plan-generate cross-wave dependency grounding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.context.models import GoalNode, StepNode
from soothe.sloop.state.schemas import LoopState, next_goal_local_step_id_start

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import StepResult

_OUTCOME_MAX = 120
_DESC_MAX = 80


def _outcome_snippet(node: StepNode) -> str:
    execution = node.execution
    if execution is None:
        return ""
    if execution.error:
        return f"error: {execution.error[:_OUTCOME_MAX]}"
    outcome = execution.outcome
    if isinstance(outcome, dict):
        summary = outcome.get("summary") or outcome.get("output") or outcome.get("type")
        if summary is not None:
            text = str(summary).replace("\n", " ").strip()
            if text:
                return text[:_OUTCOME_MAX]
    return ""


def _outcome_from_step_result(result: StepResult) -> str:
    return result.to_evidence_string(truncate=True)[:_OUTCOME_MAX]


def _format_anchor_line(*, step_id: str, status: str, description: str, outcome: str) -> str:
    desc = (description or "").replace("\n", " ").strip()
    if len(desc) > _DESC_MAX:
        desc = desc[: _DESC_MAX - 3] + "..."
    line = f"- {step_id} [{status}] {desc}"
    if outcome:
        line += f" — outcome: {outcome}"
    return line


def build_step_anchor_registry(
    *,
    goal_node: GoalNode | None = None,
    state: LoopState | None = None,
    upcoming_step_count: int = 2,
) -> str:
    """Render canonical step ids and dependency rules for plan-generate.

    Args:
        goal_node: Active goal from Context Engine (preferred source).
        state: Loop state for step_results fallback and next local id hint.
        upcoming_step_count: How many example local ids to show for the new plan.

    Returns:
        Plain-text registry block, or empty string when no prior steps exist.
    """
    completed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []

    if goal_node is not None and goal_node.steps.nodes:
        for step_id in sorted(goal_node.steps.nodes.keys()):
            node = goal_node.steps.nodes[step_id]
            outcome = _outcome_snippet(node)
            line = _format_anchor_line(
                step_id=step_id,
                status=node.status,
                description=node.description,
                outcome=outcome,
            )
            if node.status == "completed":
                completed.append(line)
            elif node.status == "pending":
                pending.append(line)
            elif node.status == "failed":
                failed.append(line)
    elif state is not None and state.step_results:
        for result in state.step_results:
            status = "completed" if result.success else "failed"
            line = _format_anchor_line(
                step_id=result.step_id,
                status=status,
                description=result.step_id,
                outcome=_outcome_from_step_result(result),
            )
            if result.success:
                completed.append(line)
            else:
                failed.append(line)

    if not completed and not pending and not failed:
        return ""

    lines: list[str] = []

    if completed:
        lines.append("Completed (valid cross-wave dependency targets — use EXACT ids):")
        lines.extend(completed)

    if pending:
        lines.append("Pending from prior plans (do not duplicate; depend on completed anchors):")
        lines.extend(pending)

    if failed:
        lines.append("Failed (do not depend on unless replanning a different approach):")
        lines.extend(failed)

    if state is not None:
        nxt = next_goal_local_step_id_start(state)
        if nxt > 1:
            end = nxt + upcoming_step_count - 1
            width = max(2, len(str(end)))
            examples = ", ".join(str(nxt + i).zfill(width) for i in range(upcoming_step_count))
            lines.append(
                f"New local ids for THIS plan only: {examples} "
                f"(scoped to PLAN-ID after ingest; not 01/02 again)."
            )

    lines.extend(
        [
            "DEPENDENCY RULES:",
            "- Same-plan edges: use local ids in this plan (e.g. 03 → 04).",
            '- Cross-plan edges: use composite ids from Completed above (e.g. MNB-03 depends on ["KFA-02"]).',
            "- Optional continues_from: list Completed composite ids when a step builds on prior work.",
            "- When a step uses prior work, list at least one Completed composite id in dependencies or continues_from.",
            "- Set execution_mode to dependency when any step has dependencies or continues_from.",
        ]
    )
    return "\n".join(lines)
