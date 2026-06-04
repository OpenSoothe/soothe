"""Tacitus subagent wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event

SUBAGENT_TACITUS_STARTED = "soothe.subagent.tacitus.started"
SUBAGENT_TACITUS_PROGRESS = "soothe.subagent.tacitus.progress"
SUBAGENT_TACITUS_GATHER_SUMMARY = "soothe.subagent.tacitus.gather.summary"
SUBAGENT_TACITUS_COMPLETED = "soothe.subagent.tacitus.completed"


class TacitusStartedEvent(SootheEvent):
    """Tacitus run started."""

    type: Literal["soothe.subagent.tacitus.started"] = SUBAGENT_TACITUS_STARTED  # type: ignore[assignment]
    topic_preview: str = ""
    effort: str = ""

    model_config = ConfigDict(extra="allow")


class TacitusProgressEvent(SootheEvent):
    """Real-time progress update during Tacitus execution."""

    type: Literal["soothe.subagent.tacitus.progress"] = SUBAGENT_TACITUS_PROGRESS  # type: ignore[assignment]
    phase: str = ""  # analyze, generate_queries, gather, summarize, reflect, synthesize
    loop_count: int = 0
    total_loops: int = 0
    sources_completed: int = 0
    total_sources: int = 0
    message: str = ""

    model_config = ConfigDict(extra="allow")


class TacitusGatherSummaryEvent(SootheEvent):
    """Brief summary after a gather batch."""

    type: Literal["soothe.subagent.tacitus.gather.summary"] = SUBAGENT_TACITUS_GATHER_SUMMARY  # type: ignore[assignment]
    query_preview: str = ""
    result_count: int = 0
    sources_touched: int = 0

    model_config = ConfigDict(extra="allow")


class TacitusCompletedEvent(SootheEvent):
    """Tacitus synthesize finished."""

    type: Literal["soothe.subagent.tacitus.completed"] = SUBAGENT_TACITUS_COMPLETED  # type: ignore[assignment]
    duration_ms: int = 0
    answer_length: int = 0
    summary: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    TacitusStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Tacitus: {topic_preview}",
)
register_event(
    TacitusProgressEvent,
    verbosity=VerbosityTier.INTERNAL,  # Progress events stay daemon-side
    summary_template="{phase}: {message}",
)
register_event(
    TacitusGatherSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Gather: {result_count} hits ({sources_touched} sources)",
)
register_event(
    TacitusCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Tacitus done ({answer_length} chars)",
)

__all__ = [
    "SUBAGENT_TACITUS_COMPLETED",
    "SUBAGENT_TACITUS_GATHER_SUMMARY",
    "SUBAGENT_TACITUS_PROGRESS",
    "SUBAGENT_TACITUS_STARTED",
    "TacitusCompletedEvent",
    "TacitusGatherSummaryEvent",
    "TacitusProgressEvent",
    "TacitusStartedEvent",
]
