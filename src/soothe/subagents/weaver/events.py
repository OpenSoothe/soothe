"""Weaver subagent events.

This module defines events for the weaver subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from dataclasses import field
from typing import Any, Literal

from pydantic import ConfigDict

from soothe.foundation.base_events import SubagentEvent


class WeaverDispatchedEvent(SubagentEvent):
    """Weaver subagent dispatched event."""

    type: Literal["soothe.subagent.weaver.dispatched"] = "soothe.subagent.weaver.dispatched"
    task: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverCompletedEvent(SubagentEvent):
    """Weaver subagent completed event."""

    type: Literal["soothe.subagent.weaver.completed"] = "soothe.subagent.weaver.completed"
    duration_ms: int = 0
    agent_name: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverAnalysisStartedEvent(SubagentEvent):
    """Weaver analysis started event."""

    type: Literal["soothe.subagent.weaver.analysis_started"] = "soothe.subagent.weaver.analysis_started"
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverAnalysisCompletedEvent(SubagentEvent):
    """Weaver analysis completed event."""

    type: Literal["soothe.subagent.weaver.analysis_completed"] = "soothe.subagent.weaver.analysis_completed"
    capabilities: list[Any] = field(default_factory=list)
    constraints: list[Any] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class WeaverReuseHitEvent(SubagentEvent):
    """Weaver reuse hit event."""

    type: Literal["soothe.subagent.weaver.reuse_hit"] = "soothe.subagent.weaver.reuse_hit"
    agent_name: str = ""
    confidence: float = 0.0

    model_config = ConfigDict(extra="allow")


class WeaverReuseMissEvent(SubagentEvent):
    """Weaver reuse miss event."""

    type: Literal["soothe.subagent.weaver.reuse_miss"] = "soothe.subagent.weaver.reuse_miss"
    best_confidence: float = 0.0

    model_config = ConfigDict(extra="allow")


class WeaverSkillifyPendingEvent(SubagentEvent):
    """Weaver skillify pending event."""

    type: Literal["soothe.subagent.weaver.skillify_pending"] = "soothe.subagent.weaver.skillify_pending"

    model_config = ConfigDict(extra="allow")


class WeaverHarmonizeStartedEvent(SubagentEvent):
    """Weaver harmonize started event."""

    type: Literal["soothe.subagent.weaver.harmonize_started"] = "soothe.subagent.weaver.harmonize_started"
    skill_count: int = 0

    model_config = ConfigDict(extra="allow")


class WeaverHarmonizeCompletedEvent(SubagentEvent):
    """Weaver harmonize completed event."""

    type: Literal["soothe.subagent.weaver.harmonize_completed"] = "soothe.subagent.weaver.harmonize_completed"
    retained: int = 0
    dropped: int = 0
    bridge_length: int = 0

    model_config = ConfigDict(extra="allow")


class WeaverGenerateStartedEvent(SubagentEvent):
    """Weaver generate started event."""

    type: Literal["soothe.subagent.weaver.generate_started"] = "soothe.subagent.weaver.generate_started"
    agent_name: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverGenerateCompletedEvent(SubagentEvent):
    """Weaver generate completed event."""

    type: Literal["soothe.subagent.weaver.generate_completed"] = "soothe.subagent.weaver.generate_completed"
    agent_name: str = ""
    path: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverValidateStartedEvent(SubagentEvent):
    """Weaver validate started event."""

    type: Literal["soothe.subagent.weaver.validate_started"] = "soothe.subagent.weaver.validate_started"
    agent_name: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverValidateCompletedEvent(SubagentEvent):
    """Weaver validate completed event."""

    type: Literal["soothe.subagent.weaver.validate_completed"] = "soothe.subagent.weaver.validate_completed"
    agent_name: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverRegistryUpdatedEvent(SubagentEvent):
    """Weaver registry updated event."""

    type: Literal["soothe.subagent.weaver.registry_updated"] = "soothe.subagent.weaver.registry_updated"
    agent_name: str = ""
    version: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverExecuteStartedEvent(SubagentEvent):
    """Weaver execute started event."""

    type: Literal["soothe.subagent.weaver.execute_started"] = "soothe.subagent.weaver.execute_started"
    agent_name: str = ""
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class WeaverExecuteCompletedEvent(SubagentEvent):
    """Weaver execute completed event."""

    type: Literal["soothe.subagent.weaver.execute_completed"] = "soothe.subagent.weaver.execute_completed"
    agent_name: str = ""
    result_length: int = 0

    model_config = ConfigDict(extra="allow")


# Register all weaver events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.foundation.verbosity_tier import VerbosityTier  # noqa: E402

# Dispatch/Complete events visible at NORMAL
register_event(
    WeaverDispatchedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Weaver: {task}",
)
register_event(
    WeaverCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Completed in {duration_ms}ms",
)

# IG-089: Internal weaver steps at DETAILED (hidden at normal verbosity)
register_event(
    WeaverAnalysisStartedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverAnalysisCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverReuseHitEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverReuseMissEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverSkillifyPendingEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverHarmonizeStartedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverHarmonizeCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverGenerateStartedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverGenerateCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverValidateStartedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverValidateCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverRegistryUpdatedEvent,
    verbosity=VerbosityTier.DETAILED,
)
register_event(
    WeaverExecuteStartedEvent,
    verbosity=VerbosityTier.NORMAL,  # Execution visible (actual task being run)
)
register_event(
    WeaverExecuteCompletedEvent,
    verbosity=VerbosityTier.NORMAL,  # Execution result visible
)

# Event type constants for convenient imports
SUBAGENT_WEAVER_DISPATCHED = "soothe.subagent.weaver.dispatched"
SUBAGENT_WEAVER_COMPLETED = "soothe.subagent.weaver.completed"
SUBAGENT_WEAVER_ANALYSIS_STARTED = "soothe.subagent.weaver.analysis_started"
SUBAGENT_WEAVER_ANALYSIS_COMPLETED = "soothe.subagent.weaver.analysis_completed"
SUBAGENT_WEAVER_REUSE_HIT = "soothe.subagent.weaver.reuse_hit"
SUBAGENT_WEAVER_REUSE_MISS = "soothe.subagent.weaver.reuse_miss"
SUBAGENT_WEAVER_SKILLIFY_PENDING = "soothe.subagent.weaver.skillify_pending"
SUBAGENT_WEAVER_HARMONIZE_STARTED = "soothe.subagent.weaver.harmonize_started"
SUBAGENT_WEAVER_HARMONIZE_COMPLETED = "soothe.subagent.weaver.harmonize_completed"
SUBAGENT_WEAVER_GENERATE_STARTED = "soothe.subagent.weaver.generate_started"
SUBAGENT_WEAVER_GENERATE_COMPLETED = "soothe.subagent.weaver.generate_completed"
SUBAGENT_WEAVER_VALIDATE_STARTED = "soothe.subagent.weaver.validate_started"
SUBAGENT_WEAVER_VALIDATE_COMPLETED = "soothe.subagent.weaver.validate_completed"
SUBAGENT_WEAVER_REGISTRY_UPDATED = "soothe.subagent.weaver.registry_updated"
SUBAGENT_WEAVER_EXECUTE_STARTED = "soothe.subagent.weaver.execute_started"
SUBAGENT_WEAVER_EXECUTE_COMPLETED = "soothe.subagent.weaver.execute_completed"

__all__ = [
    "SUBAGENT_WEAVER_ANALYSIS_COMPLETED",
    "SUBAGENT_WEAVER_ANALYSIS_STARTED",
    "SUBAGENT_WEAVER_COMPLETED",
    "SUBAGENT_WEAVER_DISPATCHED",
    "SUBAGENT_WEAVER_EXECUTE_COMPLETED",
    "SUBAGENT_WEAVER_EXECUTE_STARTED",
    "SUBAGENT_WEAVER_GENERATE_COMPLETED",
    "SUBAGENT_WEAVER_GENERATE_STARTED",
    "SUBAGENT_WEAVER_HARMONIZE_COMPLETED",
    "SUBAGENT_WEAVER_HARMONIZE_STARTED",
    "SUBAGENT_WEAVER_REGISTRY_UPDATED",
    "SUBAGENT_WEAVER_REUSE_HIT",
    "SUBAGENT_WEAVER_REUSE_MISS",
    "SUBAGENT_WEAVER_SKILLIFY_PENDING",
    "SUBAGENT_WEAVER_VALIDATE_COMPLETED",
    "SUBAGENT_WEAVER_VALIDATE_STARTED",
    "WeaverAnalysisCompletedEvent",
    "WeaverAnalysisStartedEvent",
    "WeaverCompletedEvent",
    "WeaverDispatchedEvent",
    "WeaverExecuteCompletedEvent",
    "WeaverExecuteStartedEvent",
    "WeaverGenerateCompletedEvent",
    "WeaverGenerateStartedEvent",
    "WeaverHarmonizeCompletedEvent",
    "WeaverHarmonizeStartedEvent",
    "WeaverRegistryUpdatedEvent",
    "WeaverReuseHitEvent",
    "WeaverReuseMissEvent",
    "WeaverSkillifyPendingEvent",
    "WeaverValidateCompletedEvent",
    "WeaverValidateStartedEvent",
]
