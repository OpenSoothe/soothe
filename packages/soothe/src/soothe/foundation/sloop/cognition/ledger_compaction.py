"""Compact recorded plan-phase ledger turns before they re-enter the next prompt.

The RFC-214 ledger records every plan-assess / plan-generate turn as a
(LoopHumanMessage, LoopAIMessage) pair so later turns can see prior reasoning.
Two failure modes show up in practice (trace 19c3ed3):

1. The recorded AI dump carries the prior `assessment_reasoning` verbatim.
   Structured-output models echo it on the next assess, producing repeated
   reasoning even when fresh evidence has arrived. (Ablation A2.)
2. The recorded human carries `GOAL:` (or legacy `<USER_QUERY>`). The duplicated
   goal anchors recency away from the latest evidence (ablation D1).

Volatile timestamps live on execute CoreAgent system prompts (``<TIMESTAMP>`` XML footer), not
in plan-assess/plan-generate prompts or user/ledger messages.

These helpers apply transforms at the single point where the ledger pair is
recorded so the live LLM call still sees the full rendered message — only the
*stored* copy is compacted.
"""

from __future__ import annotations

import re
from typing import Any

# Legacy format: <CONTEXT_INFO>...</CONTEXT_INFO> (multi-line block, migration)
_CONTEXT_INFO_RE = re.compile(
    r"\n?<CONTEXT_INFO>.*?</CONTEXT_INFO>\n?",
    re.DOTALL,
)

# D1 — Collapse the recorded GOAL: into a non-anchoring GOAL RECAP: so
# the next turn's GOAL: is the only one the model sees as a directive.
_GOAL_PREFIX = "GOAL:"
_GOAL_RECAP_PREFIX = "GOAL RECAP:"
_USER_QUERY_OPEN = "<USER_QUERY>"
_USER_QUERY_CLOSE = "</USER_QUERY>"
_GOAL_RECAP_OPEN = "<GOAL_RECAP>"
_GOAL_RECAP_CLOSE = "</GOAL_RECAP>"

# A2 — fields preserved on the recorded plan-assess AI dump.
_PLAN_ASSESS_LEDGER_FIELDS: frozenset[str] = frozenset(
    {"status", "goal_progress", "require_goal_completion"}
)


def compact_planning_human_content(content: str) -> str:
    """Return ledger-ready content for a recorded plan-phase HumanMessage.

    Applies D1 (rewrite ``GOAL:``/``<USER_QUERY>`` to non-anchoring recap) and
    strips legacy ``<CONTEXT_INFO>`` blocks when present.

    Args:
        content: Rendered envelope text from ``UserMessageBuilder``.

    Returns:
        Compacted content suitable for ``state.loop_messages``.
    """
    if not isinstance(content, str) or not content:
        return content

    stripped = _CONTEXT_INFO_RE.sub("", content) if _CONTEXT_INFO_RE.search(content) else content

    if _USER_QUERY_OPEN in stripped:
        stripped = stripped.replace(_USER_QUERY_OPEN, _GOAL_RECAP_OPEN).replace(
            _USER_QUERY_CLOSE, _GOAL_RECAP_CLOSE
        )
    elif stripped.startswith(_GOAL_PREFIX + "\n") or "\n" + _GOAL_PREFIX in stripped:
        stripped = stripped.replace(_GOAL_PREFIX, _GOAL_RECAP_PREFIX, 1)

    return stripped.rstrip() + "\n" if stripped.endswith(("\n", "\r")) else stripped.rstrip()


def compact_plan_assess_ai_dump(response: Any) -> str:
    """Return ledger-ready content for a recorded plan-assess AI message (A2)."""
    if response is None:
        return ""
    dump_fn = getattr(response, "model_dump", None)
    if not callable(dump_fn):
        return str(response)
    try:
        raw = dump_fn()
    except Exception:  # noqa: BLE001 — defensive: ledger must never break the loop
        return str(response)
    if not isinstance(raw, dict):
        return str(raw)
    compact = {k: v for k, v in raw.items() if k in _PLAN_ASSESS_LEDGER_FIELDS}
    if not compact:
        return str(raw)
    return str(compact)


def compact_execute_human_content(step: Any, *, envelope: str = "") -> str:
    """Return ledger-ready content for a recorded execute-step HumanMessage.

    Stores EXECUTION TASK + EXPECTED OUTPUT only. Volatile sections (WORKSPACE STATE,
    SKILL CONTEXT, EXECUTION HINTS) and predecessor context (projected separately
    into CoreAgent input) are omitted.
    """
    from soothe.foundation.sloop.prompts.user_message import (
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
