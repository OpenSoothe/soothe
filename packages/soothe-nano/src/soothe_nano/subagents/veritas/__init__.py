"""Veritas subagent: intent-grounded clarification auto-answerer (RFC-622).

Veritas is invoked by ``AutoClarificationPolicy`` when the StrangeLoop pauses on
an ``ask_user`` interrupt in autonomous mode. It is a single structured-output
LLM call (not a CoreAgent) that produces a best-effort answer from the goal's
first-principles context.

If veritas cannot answer with sufficient confidence it sets ``defer=True`` and
the loop transitions the goal to ``awaiting_clarification`` for out-of-band
resolution.
"""

from __future__ import annotations

from soothe_nano.subagents.veritas.events import (
    SUBAGENT_VERITAS_ANSWERED,
    SUBAGENT_VERITAS_DEFERRED,
    SUBAGENT_VERITAS_REQUESTED,
    VeritasAnsweredEvent,
    VeritasDeferredEvent,
    VeritasRequestedEvent,
)
from soothe_nano.subagents.veritas.implementation import answer
from soothe_nano.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
)

__all__ = [
    "SUBAGENT_VERITAS_ANSWERED",
    "SUBAGENT_VERITAS_DEFERRED",
    "SUBAGENT_VERITAS_REQUESTED",
    "VeritasAnswerSchema",
    "VeritasAnsweredEvent",
    "VeritasDeferredEvent",
    "VeritasRequestedEvent",
    "answer",
    "build_veritas_response_schema",
]
