"""Loop-tagged assistant output on the LangGraph ``messages`` stream (IG-317 / RFC-614).

Public UX surface for user-visible assistant text from the main loop: stream
``mode="messages"`` chunks whose payload carries a recognized ``phase`` (see
``LOOP_ASSISTANT_OUTPUT_PHASES``). Custom daemon events are not used for this
text path.
"""

from __future__ import annotations

from typing import Any

# Phases whose assistant text is forwarded as ``mode="messages"`` chunks (not custom).
LOOP_ASSISTANT_OUTPUT_PHASES: frozenset[str] = frozenset(
    {"goal_completion", "chitchat", "quiz", "autonomous_goal"}
)


def assistant_output_phase(msg: Any) -> str | None:
    """Return ``phase`` when ``msg`` is a loop-tagged assistant-output payload."""
    if msg is None:
        return None
    phase = getattr(msg, "phase", None)
    if isinstance(phase, str) and phase in LOOP_ASSISTANT_OUTPUT_PHASES:
        return phase
    if isinstance(msg, dict):
        p = msg.get("phase")
        if isinstance(p, str) and p in LOOP_ASSISTANT_OUTPUT_PHASES:
            return p
    return None


__all__ = ["LOOP_ASSISTANT_OUTPUT_PHASES", "assistant_output_phase"]
