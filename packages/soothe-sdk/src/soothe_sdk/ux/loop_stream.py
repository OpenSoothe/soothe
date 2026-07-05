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


# Explicit synthesis-stream end marker on ``phase=goal_completion`` wire frames.
GOAL_COMPLETION_STREAM_TERMINAL_FIELD = "stream_terminal"


def _wire_bool_field(msg: Any, field: str) -> bool:
    if isinstance(msg, dict):
        return msg.get(field) is True
    return getattr(msg, field, None) is True


def _wire_str_field(msg: Any, field: str) -> str | None:
    if isinstance(msg, dict):
        raw = msg.get(field)
    else:
        raw = getattr(msg, field, None)
    return raw if isinstance(raw, str) else None


def is_goal_completion_stream_terminal(msg: Any) -> bool:
    """Return True when a ``goal_completion`` message ends the synthesis stream.

    Clients must finalize streaming UI state on this signal even when ``content``
    is empty (adaptive chunked delivery emits a terminal frame with no text).
    """
    if assistant_output_phase(msg) != "goal_completion":
        return False
    if _wire_bool_field(msg, GOAL_COMPLETION_STREAM_TERMINAL_FIELD):
        return True
    # Older daemons may omit ``stream_terminal`` on the final content block.
    return _wire_str_field(msg, "chunk_position") == "last"


def build_goal_completion_stream_terminal_message(
    template_msg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a wire dict that marks the end of goal_completion synthesis streaming."""
    msg = dict(template_msg or {})
    msg.setdefault("type", "AIMessageChunk")
    msg["phase"] = "goal_completion"
    msg["content"] = ""
    msg["chunk_position"] = "last"
    msg[GOAL_COMPLETION_STREAM_TERMINAL_FIELD] = True
    return msg


__all__ = [
    "GOAL_COMPLETION_STREAM_TERMINAL_FIELD",
    "LOOP_ASSISTANT_OUTPUT_PHASES",
    "assistant_output_phase",
    "build_goal_completion_stream_terminal_message",
    "is_goal_completion_stream_terminal",
]
