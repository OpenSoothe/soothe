"""Origin router: maps a clarification origin to its resume station + pause mode.

Absorbs the resume-node mapping from ``clarification/origins.py`` (IG-775).
The origin *constants* and *taxonomy* (``ORIGIN_EXECUTE``,
``CLARIFICATION_ORIGINS``, ``ClarificationOrigin``, etc.) stay in
``clarification/origins.py`` because they are shared vocabulary consumed by
the policies (``InteractiveClarificationPolicy``, ``AutoClarificationPolicy``,
``ToolApprovalPipeline``), not relay mechanics.

Only the resume-node mapping moves here — it is relay routing logic
(``which station does this origin resume at?``), not clarification
classification.
"""

from __future__ import annotations

from typing import Literal

from soothe.sloop.clarification.origins import (
    CLARIFICATION_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.orchestrator.stations import EXECUTE, PLAN_REVIEW

PauseMode = Literal["interactive", "hard_defer"]
"""How the loop pauses for a given origin.

``interactive`` — pause via LangGraph ``interrupt()`` (the
``InteractiveClarificationPolicy`` suspends the graph; resume via
``Command(resume=...)``).

``hard_defer`` — pause via ``park_for_clarification`` + CE
``mark_awaiting_clarification``; resume is out-of-band (``soothe goal
answer ...``). Used when no policy is configured or the policy defers.
"""

CLARIFICATION_ORIGIN_RESUME_NODE: dict[str, str] = {
    ORIGIN_PLAN_MODE_REVIEW: PLAN_REVIEW,
    ORIGIN_EXECUTE: EXECUTE,
    ORIGIN_TOOL_APPROVAL: EXECUTE,
}


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph station that should resume.

    Returns:
        Canonical graph station name, or ``None`` when the origin is unknown
        or host-only (``rail_pause`` — not a StrangeLoop interrupt).
    """
    if not origin or origin not in CLARIFICATION_ORIGINS:
        return None
    if origin == ORIGIN_RAIL_PAUSE:
        return None
    return CLARIFICATION_ORIGIN_RESUME_NODE[origin]


def pause_mode_for_origin(origin: str | None) -> PauseMode:
    """Default pause mode for a clarification origin.

    All in-loop origins default to ``interactive`` (the policy decides whether
    to defer). ``rail_pause`` is host-only and never reaches the relay, but is
    mapped to ``hard_defer`` for completeness.
    """
    if origin == ORIGIN_RAIL_PAUSE:
        return "hard_defer"
    return "interactive"


__all__ = [
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "PauseMode",
    "pause_mode_for_origin",
    "resume_node_for_clarification_origin",
]
