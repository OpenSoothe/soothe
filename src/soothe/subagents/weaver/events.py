"""Weaver subagent events."""

from __future__ import annotations

from dataclasses import field
from typing import Any, Literal

from pydantic import ConfigDict

from soothe.core.base_events import SubagentEvent


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


__all__ = [
    "WeaverAnalysisCompletedEvent",
    "WeaverAnalysisStartedEvent",
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
