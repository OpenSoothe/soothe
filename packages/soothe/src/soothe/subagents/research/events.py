"""Research subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_RESEARCH_COMPLETED,
    SUBAGENT_RESEARCH_GATHER_SUMMARY,
    SUBAGENT_RESEARCH_STARTED,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event


class ResearchStartedEvent(SootheEvent):
    """Research run started."""

    type: Literal["soothe.subagent.research.started"] = SUBAGENT_RESEARCH_STARTED  # type: ignore[assignment]
    topic_preview: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchGatherSummaryEvent(SootheEvent):
    """Brief summary after a gather batch (metadata only)."""

    type: Literal["soothe.subagent.research.gather.summary"] = SUBAGENT_RESEARCH_GATHER_SUMMARY  # type: ignore[assignment]
    query_preview: str = ""
    result_count: int = 0
    sources_touched: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchCompletedEvent(SootheEvent):
    """Research synthesize finished."""

    type: Literal["soothe.subagent.research.completed"] = SUBAGENT_RESEARCH_COMPLETED  # type: ignore[assignment]
    duration_ms: int = 0
    answer_length: int = 0
    summary: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    ResearchStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Research: {topic_preview}",
)
register_event(
    ResearchGatherSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Gather: {result_count} hits ({sources_touched} sources)",
)
register_event(
    ResearchCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Research done ({answer_length} chars)",
)

SUBAGENT_RESEARCH_DISPATCHED = SUBAGENT_RESEARCH_STARTED
SUBAGENT_RESEARCH_COMPLETED = SUBAGENT_RESEARCH_COMPLETED
SUBAGENT_RESEARCH_GATHER_SUMMARY = SUBAGENT_RESEARCH_GATHER_SUMMARY

__all__ = [
    "SUBAGENT_RESEARCH_COMPLETED",
    "SUBAGENT_RESEARCH_DISPATCHED",
    "SUBAGENT_RESEARCH_GATHER_SUMMARY",
    "ResearchCompletedEvent",
    "ResearchGatherSummaryEvent",
    "ResearchStartedEvent",
]
