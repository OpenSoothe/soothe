"""Skillify subagent events."""

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


__all__ = [
    "SkillifyIndexFailedEvent",
    "SkillifyIndexStartedEvent",
    "SkillifyIndexUnchangedEvent",
    "SkillifyIndexUpdatedEvent",
    "SkillifyIndexingPendingEvent",
    "SkillifyRetrieveCompletedEvent",
    "SkillifyRetrieveNotReadyEvent",
    "SkillifyRetrieveStartedEvent",
]
