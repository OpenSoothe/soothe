"""Explore subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent, SubagentEvent
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_EXPLORE_COMPLETED,
    SUBAGENT_EXPLORE_MILESTONE,
    SUBAGENT_EXPLORE_STARTED,
    SUBAGENT_EXPLORE_STEP_COMPLETED,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event


class ExploreStartedEvent(SootheEvent):
    """Explore search started."""

    type: Literal["soothe.subagent.explore.started"] = SUBAGENT_EXPLORE_STARTED  # type: ignore[assignment]
    search_target: str = ""
    thoroughness: str = ""

    model_config = ConfigDict(extra="allow")


class ExploreMilestoneEvent(SootheEvent):
    """Assessment milestone (decision + counts only)."""

    type: Literal["soothe.subagent.explore.milestone"] = SUBAGENT_EXPLORE_MILESTONE  # type: ignore[assignment]
    decision: str = ""
    findings_count: int = 0
    iterations_used: int = 0

    model_config = ConfigDict(extra="allow")


class ExploreStepCompletedEvent(SubagentEvent):
    """One explore tool call completed (metadata only)."""

    type: Literal["soothe.subagent.explore.step.completed"] = SUBAGENT_EXPLORE_STEP_COMPLETED  # type: ignore[assignment]
    tool_name: str = ""
    args_preview: str = ""
    result_preview: str = ""

    model_config = ConfigDict(extra="allow")


class ExploreCompletedEvent(SootheEvent):
    """Explore finished synthesizing."""

    type: Literal["soothe.subagent.explore.completed"] = SUBAGENT_EXPLORE_COMPLETED  # type: ignore[assignment]
    total_findings: int = 0
    thoroughness: str = ""
    iterations_used: int = 0
    duration_ms: int = 0
    search_target: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    ExploreStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Explore: {search_target}",
)
register_event(
    ExploreMilestoneEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="{decision} ({findings_count} findings)",
)
register_event(
    ExploreStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {args_preview}",
)
register_event(
    ExploreCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Explore done ({total_findings} findings)",
)

SUBAGENT_EXPLORE_STARTED = SUBAGENT_EXPLORE_STARTED
SUBAGENT_EXPLORE_MILESTONE = SUBAGENT_EXPLORE_MILESTONE
SUBAGENT_EXPLORE_STEP_COMPLETED = SUBAGENT_EXPLORE_STEP_COMPLETED
SUBAGENT_EXPLORE_COMPLETED = SUBAGENT_EXPLORE_COMPLETED

__all__ = [
    "SUBAGENT_EXPLORE_COMPLETED",
    "SUBAGENT_EXPLORE_MILESTONE",
    "SUBAGENT_EXPLORE_STEP_COMPLETED",
    "SUBAGENT_EXPLORE_STARTED",
    "ExploreCompletedEvent",
    "ExploreMilestoneEvent",
    "ExploreStepCompletedEvent",
    "ExploreStartedEvent",
]
