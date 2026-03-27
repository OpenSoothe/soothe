"""Goals tool events.

This module defines events for goal management tools.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class GoalCreatedEvent(ToolEvent):
    """Goal created event."""

    type: Literal["soothe.tool.goals.created"] = "soothe.tool.goals.created"
    goal_id: str = ""
    description: str = ""
    priority: int | str = ""

    model_config = ConfigDict(extra="allow")


class GoalCompletedEvent(ToolEvent):
    """Goal completed event."""

    type: Literal["soothe.tool.goals.completed"] = "soothe.tool.goals.completed"
    goal_id: str = ""

    model_config = ConfigDict(extra="allow")


class GoalFailedEvent(ToolEvent):
    """Goal failed event."""

    type: Literal["soothe.tool.goals.failed"] = "soothe.tool.goals.failed"
    goal_id: str = ""
    reason: str = ""

    model_config = ConfigDict(extra="allow")


class GoalListedEvent(ToolEvent):
    """Goal listed event."""

    type: Literal["soothe.tool.goals.listed"] = "soothe.tool.goals.listed"
    count: int = 0
    status_filter: str = ""

    model_config = ConfigDict(extra="allow")


# Register all goals events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    GoalCreatedEvent,
    verbosity="tool_activity",
    summary_template="Goal created: {description}",
)
register_event(
    GoalCompletedEvent,
    verbosity="tool_activity",
    summary_template="Goal completed: {goal_id}",
)
register_event(
    GoalFailedEvent,
    verbosity="tool_activity",
    summary_template="Goal failed: {reason}",
)
register_event(
    GoalListedEvent,
    verbosity="tool_activity",
    summary_template="Listed {count} goals",
)

# Event type constants for convenient imports
TOOL_GOALS_CREATED = "soothe.tool.goals.created"
TOOL_GOALS_COMPLETED = "soothe.tool.goals.completed"
TOOL_GOALS_FAILED = "soothe.tool.goals.failed"
TOOL_GOALS_LISTED = "soothe.tool.goals.listed"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_GOALS_COMPLETED",
    "TOOL_GOALS_CREATED",
    "TOOL_GOALS_FAILED",
    "TOOL_GOALS_LISTED",
    # Event classes (alphabetically)
    "GoalCompletedEvent",
    "GoalCreatedEvent",
    "GoalFailedEvent",
    "GoalListedEvent",
]
