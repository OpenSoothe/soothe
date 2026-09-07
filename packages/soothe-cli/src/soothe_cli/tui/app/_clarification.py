"""Clarification wire-content formatting for plan-review and tool-approval submits.

Pure utility — no mixin state dependency. Extracted from `_execution.py` to
keep the execution mixin focused on agent execution and message routing.
"""

from __future__ import annotations

_PLAN_REVIEW_ACTIONS = frozenset({"Approve", "Reject", "Refine"})
_TOOL_APPROVAL_ACTIONS = frozenset({"Approve", "Reject"})


def clarification_wire_content(answers: list[str], *, origin_node: str = "") -> str:
    """Human-readable turn content for a clarification submit (not a new goal).

    Option-selector actions use a stable ``<prefix>: …`` header so a dropped
    ``clarification_answer`` flag cannot turn a bare action into Pass1 TASK.
    Plan review → ``Plan review:`` (Refine carries refinement text in
    ``answers[1]``). Tool approval → ``Tool approval:``.
    """
    non_empty = [a for a in answers if str(a).strip()]
    if not non_empty:
        return ""
    first = str(answers[0]).strip() if answers else ""
    is_tool_approval = origin_node == "tool_approval"
    is_selector_action = first in _PLAN_REVIEW_ACTIONS or first in _TOOL_APPROVAL_ACTIONS
    if is_selector_action:
        refinement = str(answers[1]).strip() if len(answers) > 1 else ""
        # Origin-aware prefix; when origin is unknown (legacy caller), default
        # to "Plan review" to preserve the pre-RFC behavior where the action
        # label alone selected the plan-review prefix.
        prefix = "Tool approval" if is_tool_approval else "Plan review"
        if refinement:
            return f"{prefix}: {first} — {refinement}"
        return f"{prefix}: {first}"
    if len(non_empty) == 1:
        return non_empty[0]
    return " | ".join(f"A{i + 1}: {a}" for i, a in enumerate(answers) if str(a).strip())
