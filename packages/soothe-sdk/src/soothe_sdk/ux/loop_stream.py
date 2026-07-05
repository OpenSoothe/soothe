"""Loop-tagged assistant output on the LangGraph ``messages`` stream (IG-317 / RFC-614).

Public UX surface for user-visible assistant text from the main loop: stream
``mode="messages"`` chunks whose payload carries a recognized ``phase`` (see
``LOOP_ASSISTANT_OUTPUT_PHASES``). Custom daemon events are not used for this
text path.

Headless CLI relies on these phases for stdout (IG-343). Delegate-only answers may appear
as an extra ``phase=goal_completion`` replay after Act when sourced from ``task`` returns (IG-355).

Daemon ``intent_hint`` direct model turns emit a single assistant chunk tagged
``phase=<hint>`` (``text_completion``, ``image_to_text``, ``ocr``, ``embed``) so
clients apply the same preview/stream rules as other user-visible loop output.
Legacy ``direct_model`` phase may still appear from older daemon versions.
"""

from __future__ import annotations

from typing import Any

# Phases whose assistant text is forwarded as ``mode="messages"`` chunks (not custom).
LOOP_ASSISTANT_OUTPUT_PHASES: frozenset[str] = frozenset(
    {
        "goal_completion",
        "quiz",
        "chitchat",
        "trivial",
        "autonomous_goal",
        "direct_model",
        "text_completion",
        "image_to_text",
        "ocr",
        "embed",
        "plan_direct",
    }
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
