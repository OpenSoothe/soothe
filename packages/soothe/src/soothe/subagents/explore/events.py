"""Explore subagent events.

Defines and registers events for the explore subagent (RFC-613).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.events import SootheEvent


class ExploreStartedEvent(SootheEvent):
    """Explore search started event."""

    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.started"] = "soothe.capability.explore.started"
    search_target: str = ""
    thoroughness: str = ""


class ExploreExecutingEvent(SootheEvent):
    """Explore tool executing event."""

    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.executing"] = "soothe.capability.explore.executing"
    tool_name: str = ""
    results_count: int = 0


class ExploreAssessingEvent(SootheEvent):
    """Explore assessment event."""

    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.assessing"] = "soothe.capability.explore.assessing"
    decision: str = ""  # "continue" | "adjust" | "finish"
    findings_count: int = 0
    iterations_used: int = 0


class ExploreCompletedEvent(SootheEvent):
    """Explore search completed event."""

    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.completed"] = "soothe.capability.explore.completed"
    total_findings: int = 0
    thoroughness: str = ""
    iterations_used: int = 0
    duration_ms: int = 0


# Register all explore events with the global registry
from soothe_sdk.verbosity import VerbosityTier  # noqa: E402

from soothe.core.event_catalog import register_event  # noqa: E402

# Start/complete events visible at NORMAL
register_event(
    ExploreStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Explore: {search_target} ({thoroughness})",
)
register_event(
    ExploreCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Explore done: {total_findings} findings ({iterations_used} iters, {duration_ms}ms)",
)

# Internal steps at DETAILED
register_event(
    ExploreExecutingEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Executing: {tool_name} ({results_count} results)",
)
register_event(
    ExploreAssessingEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Assessed: {decision} ({findings_count} findings, iter {iterations_used})",
)

# Event type constants for convenient imports
SUBAGENT_EXPLORE_STARTED = "soothe.capability.explore.started"
SUBAGENT_EXPLORE_EXECUTING = "soothe.capability.explore.executing"
SUBAGENT_EXPLORE_ASSESSING = "soothe.capability.explore.assessing"
SUBAGENT_EXPLORE_COMPLETED = "soothe.capability.explore.completed"

__all__ = [
    # Event type constants
    "SUBAGENT_EXPLORE_ASSESSING",
    "SUBAGENT_EXPLORE_COMPLETED",
    "SUBAGENT_EXPLORE_EXECUTING",
    "SUBAGENT_EXPLORE_STARTED",
    # Event classes
    "ExploreAssessingEvent",
    "ExploreCompletedEvent",
    "ExploreExecutingEvent",
    "ExploreStartedEvent",
]
