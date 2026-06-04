"""Wire events for the clarification relay (RFC-622)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import (
    LOOP_CLARIFICATION_ANSWERED,
    LOOP_CLARIFICATION_DEFERRED,
    LOOP_CLARIFICATION_REQUESTED,
    SootheEvent,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event


class ClarificationRequestedEvent(SootheEvent):
    """Fired when ``await_clarification`` enters with a pending question."""

    type: Literal["soothe.loop.clarification.requested"] = LOOP_CLARIFICATION_REQUESTED  # type: ignore[assignment]
    questions: list[str] = []
    origin_node: str = ""
    mode: Literal["manual", "auto"] = "manual"

    model_config = ConfigDict(extra="allow")


class ClarificationAnsweredEvent(SootheEvent):
    """Fired after the policy returns an answer."""

    type: Literal["soothe.loop.clarification.answered"] = LOOP_CLARIFICATION_ANSWERED  # type: ignore[assignment]
    source: Literal["human", "veritas", "fallback"] = "human"
    confidence: float | None = None
    defer: bool = False

    model_config = ConfigDict(extra="allow")


class ClarificationDeferredEvent(SootheEvent):
    """Fired when the policy raises ``ClarificationDeferredError``."""

    type: Literal["soothe.loop.clarification.deferred"] = LOOP_CLARIFICATION_DEFERRED  # type: ignore[assignment]
    reason: str = ""
    question_summary: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    ClarificationRequestedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification needed: {questions}",
)
register_event(
    ClarificationAnsweredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification answered ({source})",
)
register_event(
    ClarificationDeferredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification deferred: {reason}",
)


__all__ = [
    "LOOP_CLARIFICATION_ANSWERED",
    "LOOP_CLARIFICATION_DEFERRED",
    "LOOP_CLARIFICATION_REQUESTED",
    "ClarificationAnsweredEvent",
    "ClarificationDeferredEvent",
    "ClarificationRequestedEvent",
]
