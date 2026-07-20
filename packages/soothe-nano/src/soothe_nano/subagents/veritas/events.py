"""Veritas subagent wire events (RFC-622)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events import register_event

SUBAGENT_VERITAS_REQUESTED = "soothe.subagent.veritas.requested"
SUBAGENT_VERITAS_ANSWERED = "soothe.subagent.veritas.answered"
SUBAGENT_VERITAS_DEFERRED = "soothe.subagent.veritas.deferred"


class VeritasRequestedEvent(SootheEvent):
    """Veritas was invoked for a clarification."""

    type: Literal["soothe.subagent.veritas.requested"] = SUBAGENT_VERITAS_REQUESTED  # type: ignore[assignment]
    question_count: int = 0
    origin_node: str = ""

    model_config = ConfigDict(extra="allow")


class VeritasAnsweredEvent(SootheEvent):
    """Veritas returned an answer."""

    type: Literal["soothe.subagent.veritas.answered"] = SUBAGENT_VERITAS_ANSWERED  # type: ignore[assignment]
    confidence: float = 0.0
    defer: bool = False
    rationale_preview: str = ""

    model_config = ConfigDict(extra="allow")


class VeritasDeferredEvent(SootheEvent):
    """Veritas chose to defer rather than answer."""

    type: Literal["soothe.subagent.veritas.deferred"] = SUBAGENT_VERITAS_DEFERRED  # type: ignore[assignment]
    reason: str = ""
    confidence: float = 0.0

    model_config = ConfigDict(extra="allow")


register_event(
    VeritasRequestedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Veritas asked ({question_count} q)",
)
register_event(
    VeritasAnsweredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Veritas answered (conf={confidence:.2f})",
)
register_event(
    VeritasDeferredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Veritas deferred: {reason}",
)


__all__ = [
    "SUBAGENT_VERITAS_ANSWERED",
    "SUBAGENT_VERITAS_DEFERRED",
    "SUBAGENT_VERITAS_REQUESTED",
    "VeritasAnsweredEvent",
    "VeritasDeferredEvent",
    "VeritasRequestedEvent",
]
