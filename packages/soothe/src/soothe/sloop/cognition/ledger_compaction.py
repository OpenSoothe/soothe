"""Compact recorded plan-phase ledger turns before they re-enter the next prompt.

The RFC-214 ledger records plan-generate turns as (LoopHumanMessage, LoopAIMessage)
pairs so later turns can see prior reasoning. Plan-assess pairs are no longer
recorded (IG-557); assess continuity uses CE ``GoalNode.last_assessment``.

The recorded human may carry ``GOAL:``. The duplicated goal anchors recency away
from the latest evidence (ablation D1). ``compact_planning_human_content`` rewrites
``GOAL:`` to a non-anchoring recap at record time so the live LLM call still sees
the full rendered message — only the stored copy is compacted.
"""

from __future__ import annotations

from typing import Any

# D1 — Collapse the recorded GOAL: into a non-anchoring GOAL RECAP: so
# the next turn's GOAL: is the only one the model sees as a directive.
_GOAL_PREFIX = "GOAL:"
_GOAL_RECAP_PREFIX = "GOAL RECAP:"


def compact_planning_human_content(content: str) -> str:
    """Return ledger-ready content for a recorded plan-phase HumanMessage.

    Applies D1 (rewrite ``GOAL:`` to non-anchoring recap) when present.

    Args:
        content: Rendered envelope text from ``UserMessageBuilder``.

    Returns:
        Compacted content suitable for ``state.loop_messages``.
    """
    if not isinstance(content, str) or not content:
        return content

    stripped = content
    if stripped.startswith(_GOAL_PREFIX + "\n") or "\n" + _GOAL_PREFIX in stripped:
        stripped = stripped.replace(_GOAL_PREFIX, _GOAL_RECAP_PREFIX, 1)

    return stripped.rstrip() + "\n" if stripped.endswith(("\n", "\r")) else stripped.rstrip()


def compact_execute_human_content(step: Any, *, envelope: str = "") -> str:
    """Return ledger-ready content for a recorded execute-step HumanMessage.

    Stores EXECUTION TASK + EXPECTED OUTPUT only. Volatile sections (WORKSPACE STATE,
    SKILL CONTEXT, INSTRUCTIONS, EXECUTION METADATA) and predecessor context (projected separately
    into CoreAgent input) are omitted.
    """
    from soothe.sloop.prompts.user_message import (
        EXECUTION_TASK_LABEL,
        flatten_user_message_content,
    )

    brief = (step.full_description or step.description or "").strip()
    if not brief and envelope:
        brief = flatten_user_message_content(envelope)

    sections: list[str] = [f"{EXECUTION_TASK_LABEL}:\n{brief}"]

    expected = (getattr(step, "expected_output", None) or "").strip()
    if expected:
        sections.append(f"EXPECTED OUTPUT:\n{expected}")

    return "\n\n".join(sections).strip()
