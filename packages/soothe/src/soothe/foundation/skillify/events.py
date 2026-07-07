"""Skillify service wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.foundation.events import register_event

SKILLIFY_RETRIEVE_COMPLETED = "soothe.skillify.retrieve_completed"
SKILLIFY_INDEX_STARTED = "soothe.skillify.index_started"
SKILLIFY_INDEX_UPDATED = "soothe.skillify.index_updated"
SKILLIFY_INDEX_UNCHANGED = "soothe.skillify.index_unchanged"
SKILLIFY_INDEX_FAILED = "soothe.skillify.index_failed"


class SkillifyRetrieveCompletedEvent(SubagentEvent):
    type: Literal["soothe.skillify.retrieve_completed"] = SKILLIFY_RETRIEVE_COMPLETED  # type: ignore[assignment]
    query: str = ""
    result_count: int = 0
    top_score: float = 0.0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexStartedEvent(SubagentEvent):
    type: Literal["soothe.skillify.index_started"] = SKILLIFY_INDEX_STARTED  # type: ignore[assignment]
    collection: str = ""

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUpdatedEvent(SubagentEvent):
    type: Literal["soothe.skillify.index_updated"] = SKILLIFY_INDEX_UPDATED  # type: ignore[assignment]
    new: int = 0
    changed: int = 0
    deleted: int = 0
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexUnchangedEvent(SubagentEvent):
    type: Literal["soothe.skillify.index_unchanged"] = SKILLIFY_INDEX_UNCHANGED  # type: ignore[assignment]
    total: int = 0

    model_config = ConfigDict(extra="allow")


class SkillifyIndexFailedEvent(SubagentEvent):
    type: Literal["soothe.skillify.index_failed"] = SKILLIFY_INDEX_FAILED  # type: ignore[assignment]

    model_config = ConfigDict(extra="allow")


register_event(
    SkillifyRetrieveCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Skillify found {result_count} skills",
)
