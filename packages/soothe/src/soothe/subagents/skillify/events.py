"""Skillify subagent wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.foundation.events import register_event

SUBAGENT_SKILLIFY_DISPATCHED = "soothe.subagent.skillify.dispatched"
SUBAGENT_SKILLIFY_COMPLETED = "soothe.subagent.skillify.completed"
SUBAGENT_SKILLIFY_INDEXING_PENDING = "soothe.subagent.skillify.indexing_pending"
SUBAGENT_SKILLIFY_RETRIEVE_STARTED = "soothe.subagent.skillify.retrieve_started"
SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED = "soothe.subagent.skillify.retrieve_completed"
SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY = "soothe.subagent.skillify.retrieve_not_ready"
SUBAGENT_SKILLIFY_INDEX_STARTED = "soothe.subagent.skillify.index_started"
SUBAGENT_SKILLIFY_INDEX_UPDATED = "soothe.subagent.skillify.index_updated"
SUBAGENT_SKILLIFY_INDEX_UNCHANGED = "soothe.subagent.skillify.index_unchanged"
SUBAGENT_SKILLIFY_INDEX_FAILED = "soothe.subagent.skillify.index_failed"


class SkillifyDispatchedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.dispatched"] = SUBAGENT_SKILLIFY_DISPATCHED  # type: ignore[assignment]
    task: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.completed"] = SUBAGENT_SKILLIFY_COMPLETED  # type: ignore[assignment]
    duration_ms: int = 0
    result_count: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexingPendingEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.indexing_pending"] = SUBAGENT_SKILLIFY_INDEXING_PENDING  # type: ignore[assignment]
    query: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_started"] = SUBAGENT_SKILLIFY_RETRIEVE_STARTED  # type: ignore[assignment]
    query: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_completed"] = (
        SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED  # type: ignore[assignment]
    )
    query: str = ""
    result_count: int = 0
    top_score: float = 0.0

    model_config = ConfigDict(extra="allow")


class SkillifyRetrieveNotReadyEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_not_ready"] = (
        SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY  # type: ignore[assignment]
    )
    message: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyIndexStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_started"] = SUBAGENT_SKILLIFY_INDEX_STARTED  # type: ignore[assignment]
    collection: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUpdatedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_updated"] = SUBAGENT_SKILLIFY_INDEX_UPDATED  # type: ignore[assignment]
    new: int = 0
    changed: int = 0
    deleted: int = 0
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUnchangedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_unchanged"] = SUBAGENT_SKILLIFY_INDEX_UNCHANGED  # type: ignore[assignment]
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexFailedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_failed"] = SUBAGENT_SKILLIFY_INDEX_FAILED  # type: ignore[assignment]

    model_config = ConfigDict(extra="allow")


register_event(
    SkillifyDispatchedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Skillify: {task}",
)
register_event(
    SkillifyCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Skillify done ({result_count} skills)",
)
register_event(
    SkillifyRetrieveCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Skillify found {result_count} skills",
)

__all__ = [
    "SUBAGENT_SKILLIFY_COMPLETED",
    "SUBAGENT_SKILLIFY_DISPATCHED",
    "SUBAGENT_SKILLIFY_INDEX_FAILED",
    "SUBAGENT_SKILLIFY_INDEX_STARTED",
    "SUBAGENT_SKILLIFY_INDEX_UNCHANGED",
    "SUBAGENT_SKILLIFY_INDEX_UPDATED",
    "SUBAGENT_SKILLIFY_INDEXING_PENDING",
    "SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED",
    "SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY",
    "SUBAGENT_SKILLIFY_RETRIEVE_STARTED",
    "SkillifyCompletedEvent",
    "SkillifyDispatchedEvent",
    "SkillifyIndexFailedEvent",
    "SkillifyIndexStartedEvent",
    "SkillifyIndexUnchangedEvent",
    "SkillifyIndexUpdatedEvent",
    "SkillifyIndexingPendingEvent",
    "SkillifyRetrieveCompletedEvent",
    "SkillifyRetrieveNotReadyEvent",
    "SkillifyRetrieveStartedEvent",
]
