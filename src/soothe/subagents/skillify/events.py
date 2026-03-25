"""Skillify subagent events.

This module defines events for the skillify subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import SubagentEvent


class SkillifyIndexingPendingEvent(SubagentEvent):
    """Skillify indexing pending event."""

    type: Literal["soothe.subagent.skillify.indexing_pending"] = "soothe.subagent.skillify.indexing_pending"
    query: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveStartedEvent(SubagentEvent):
    """Skillify retrieve started event."""

    type: Literal["soothe.subagent.skillify.retrieve_started"] = "soothe.subagent.skillify.retrieve_started"
    query: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveCompletedEvent(SubagentEvent):
    """Skillify retrieve completed event."""

    type: Literal["soothe.subagent.skillify.retrieve_completed"] = "soothe.subagent.skillify.retrieve_completed"
    query: str = ""
    result_count: int = 0
    top_score: float = 0.0

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveNotReadyEvent(SubagentEvent):
    """Skillify retrieve not ready event."""

    type: Literal["soothe.subagent.skillify.retrieve_not_ready"] = "soothe.subagent.skillify.retrieve_not_ready"
    message: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyIndexStartedEvent(SubagentEvent):
    """Skillify index started event."""

    type: Literal["soothe.subagent.skillify.index_started"] = "soothe.subagent.skillify.index_started"
    collection: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUpdatedEvent(SubagentEvent):
    """Skillify index updated event."""

    type: Literal["soothe.subagent.skillify.index_updated"] = "soothe.subagent.skillify.index_updated"
    new: int = 0
    changed: int = 0
    deleted: int = 0
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUnchangedEvent(SubagentEvent):
    """Skillify index unchanged event."""

    type: Literal["soothe.subagent.skillify.index_unchanged"] = "soothe.subagent.skillify.index_unchanged"
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexFailedEvent(SubagentEvent):
    """Skillify index failed event."""

    type: Literal["soothe.subagent.skillify.index_failed"] = "soothe.subagent.skillify.index_failed"

    model_config = ConfigDict(extra="allow")


# Register all skillify events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(SkillifyIndexingPendingEvent)
register_event(SkillifyRetrieveStartedEvent)
register_event(SkillifyRetrieveCompletedEvent)
register_event(SkillifyRetrieveNotReadyEvent)
register_event(SkillifyIndexStartedEvent)
register_event(SkillifyIndexUpdatedEvent)
register_event(SkillifyIndexUnchangedEvent)
register_event(SkillifyIndexFailedEvent)

# Event type constants for convenient imports
SUBAGENT_SKILLIFY_INDEXING_PENDING = "soothe.subagent.skillify.indexing_pending"
SUBAGENT_SKILLIFY_RETRIEVE_STARTED = "soothe.subagent.skillify.retrieve_started"
SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED = "soothe.subagent.skillify.retrieve_completed"
SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY = "soothe.subagent.skillify.retrieve_not_ready"
SUBAGENT_SKILLIFY_INDEX_STARTED = "soothe.subagent.skillify.index_started"
SUBAGENT_SKILLIFY_INDEX_UPDATED = "soothe.subagent.skillify.index_updated"
SUBAGENT_SKILLIFY_INDEX_UNCHANGED = "soothe.subagent.skillify.index_unchanged"
SUBAGENT_SKILLIFY_INDEX_FAILED = "soothe.subagent.skillify.index_failed"

__all__ = [
    "SUBAGENT_SKILLIFY_INDEXING_PENDING",
    "SUBAGENT_SKILLIFY_INDEX_FAILED",
    "SUBAGENT_SKILLIFY_INDEX_STARTED",
    "SUBAGENT_SKILLIFY_INDEX_UNCHANGED",
    "SUBAGENT_SKILLIFY_INDEX_UPDATED",
    "SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED",
    "SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY",
    "SUBAGENT_SKILLIFY_RETRIEVE_STARTED",
    "SkillifyIndexFailedEvent",
    "SkillifyIndexStartedEvent",
    "SkillifyIndexUnchangedEvent",
    "SkillifyIndexUpdatedEvent",
    "SkillifyIndexingPendingEvent",
    "SkillifyRetrieveCompletedEvent",
    "SkillifyRetrieveNotReadyEvent",
    "SkillifyRetrieveStartedEvent",
]
