"""Compact recorded plan-phase ledger turns before they re-enter the next prompt.

The RFC-214 ledger records every plan-assess / plan-generate turn as a
(LoopHumanMessage, LoopAIMessage) pair so later turns can see prior reasoning.
Two failure modes show up in practice (trace 19c3ed3):

1. The recorded AI dump carries the prior `assessment_reasoning` verbatim.
   Structured-output models echo it on the next assess, producing repeated
   reasoning even when fresh evidence has arrived. (Ablation A2.)
2. The recorded human carries `<USER_QUERY>` and a per-turn `<CONTEXT_INFO>`
   block. The duplicated goal anchors recency away from the latest evidence
   (ablation D1), and the volatile timestamp inside `<CONTEXT_INFO>` breaks
   the prompt-cache prefix on every assess (ablation C1).

These helpers apply the three transforms at the single point where the ledger
pair is recorded so the live LLM call still sees the full rendered envelope —
only the *stored* copy is compacted.
"""

from __future__ import annotations

import re
from typing import Any

# C1 — `<CONTEXT_INFO>...</CONTEXT_INFO>` is volatile (timestamp/date) and
# should not enter the cache key when the same envelope is replayed.
_CONTEXT_INFO_RE = re.compile(
    r"\n?<CONTEXT_INFO>.*?</CONTEXT_INFO>\n?",
    re.DOTALL,
)

# D1 — collapse the recorded `<USER_QUERY>` into a non-anchoring recap tag so
# the next turn's `<USER_QUERY>` is the only one the model sees as a directive.
_USER_QUERY_OPEN = "<USER_QUERY>"
_USER_QUERY_CLOSE = "</USER_QUERY>"
_GOAL_RECAP_OPEN = "<GOAL_RECAP>"
_GOAL_RECAP_CLOSE = "</GOAL_RECAP>"

# A2 — fields preserved on the recorded plan-assess AI dump. Anything outside
# this set (notably `assessment_reasoning`) is dropped before stringification.
_PLAN_ASSESS_LEDGER_FIELDS: frozenset[str] = frozenset(
    {"status", "goal_progress", "require_goal_completion"}
)


def compact_planning_human_content(content: str) -> str:
    """Return ledger-ready content for a recorded plan-phase HumanMessage.

    Applies C1 (strip `<CONTEXT_INFO>`) and D1 (rewrite `<USER_QUERY>` to a
    non-anchoring `<GOAL_RECAP>`). The original string is returned unchanged
    when neither marker is present, so this is safe to call on any content.

    Args:
        content: Rendered envelope text from ``build_plan_context_envelope``.

    Returns:
        Compacted content suitable for ``state.loop_messages``.
    """
    if not isinstance(content, str) or not content:
        return content
    stripped = _CONTEXT_INFO_RE.sub("", content)
    if _USER_QUERY_OPEN in stripped:
        stripped = stripped.replace(_USER_QUERY_OPEN, _GOAL_RECAP_OPEN).replace(
            _USER_QUERY_CLOSE, _GOAL_RECAP_CLOSE
        )
    return stripped.rstrip() + "\n" if stripped.endswith(("\n", "\r")) else stripped.rstrip()


def compact_plan_assess_ai_dump(response: Any) -> str:
    """Return ledger-ready content for a recorded plan-assess AI message (A2).

    Drops the free-form ``assessment_reasoning`` field so the next assess does
    not anchor on the prior reasoning text. The structured signal
    (``status``, ``goal_progress``, ``require_goal_completion``) is preserved
    so plan-generate and downstream auditing still see the decision.

    Falls back to ``str(response)`` when ``response`` is not a Pydantic model
    or when no recognized fields are present.

    Args:
        response: Parsed ``StatusAssessment`` (or any pydantic model with
            ``model_dump``); plain strings/None are passed through unchanged.

    Returns:
        String content to store in ``LoopAIMessage.content``.
    """
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
        # Unexpected schema — fall back to a deterministic string of the dict
        # rather than dropping the turn silently.
        return str(raw)
    return str(compact)
