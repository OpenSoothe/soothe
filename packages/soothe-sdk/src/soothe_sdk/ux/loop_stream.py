"""Loop-tagged assistant output on the LangGraph ``messages`` stream.

Public UX surface for user-visible assistant text from the main loop: stream
``mode="messages"`` chunks whose payload carries a recognized ``phase`` (see
``LOOP_ASSISTANT_OUTPUT_PHASES``). Custom events are not used for this
text path.

Headless CLI relies on these phases for stdout. Delegate-only answers may appear
as an extra ``phase=goal_completion`` replay after Act when sourced from ``task`` returns.

``intent_hint`` turns emit a single assistant chunk tagged
``phase=<hint>`` (``text_completion``, ``image_to_text``, ``ocr``, ``embed``) so
clients apply the same preview/stream rules as other user-visible loop output.
"""

from __future__ import annotations

from typing import Any

# Phases whose assistant text is forwarded as ``mode="messages"`` chunks (not custom).
LOOP_ASSISTANT_OUTPUT_PHASES: frozenset[str] = frozenset(
    {
        "goal_completion",
        "goal_interrupted",  # Non-success terminal marker (cancel/fatal/max-iter)
        "chitchat",
        "autonomous_goal",
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


# Explicit synthesis-stream end marker on assistant wire frames.
GOAL_COMPLETION_STREAM_TERMINAL_FIELD = "stream_terminal"


def _wire_bool_field(msg: Any, field: str) -> bool:
    if isinstance(msg, dict):
        return msg.get(field) is True
    return getattr(msg, field, None) is True


def is_stream_terminal_wire_dict(msg: dict[str, Any]) -> bool:
    """Return True when a wire message dict marks the end of an LLM stream."""
    if not msg:
        return False
    return msg.get(GOAL_COMPLETION_STREAM_TERMINAL_FIELD) is True


def is_stream_terminal(msg: Any) -> bool:
    """Return True when a message marks the end of an assistant LLM stream."""
    if isinstance(msg, dict):
        return is_stream_terminal_wire_dict(msg)
    return _wire_bool_field(msg, GOAL_COMPLETION_STREAM_TERMINAL_FIELD)


def is_goal_completion_stream_terminal(msg: Any) -> bool:
    """Return True when a ``goal_completion`` message ends the synthesis stream."""
    if assistant_output_phase(msg) != "goal_completion":
        return False
    return is_stream_terminal(msg)


__all__ = [
    "GOAL_COMPLETION_STREAM_TERMINAL_FIELD",
    "LOOP_ASSISTANT_OUTPUT_PHASES",
    "assistant_output_phase",
    "is_goal_completion_stream_terminal",
    "is_stream_terminal",
    "is_stream_terminal_wire_dict",
]
