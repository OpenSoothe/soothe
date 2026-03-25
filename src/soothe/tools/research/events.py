"""Research tool events."""

from __future__ import annotations

from dataclasses import field
from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import SootheEvent


class ResearchAnalyzeEvent(SootheEvent):
    """Research analyze event."""

    type: Literal["soothe.tool.research.analyze"] = "soothe.tool.research.analyze"
    topic: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchSubQuestionsEvent(SootheEvent):
    """Research sub questions event."""

    type: Literal["soothe.tool.research.sub_questions"] = "soothe.tool.research.sub_questions"
    count: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchQueriesGeneratedEvent(SootheEvent):
    """Research queries generated event."""

    type: Literal["soothe.tool.research.queries_generated"] = "soothe.tool.research.queries_generated"
    queries: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchGatherEvent(SootheEvent):
    """Research gather event."""

    type: Literal["soothe.tool.research.gather"] = "soothe.tool.research.gather"
    query: str = ""
    domain: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchGatherDoneEvent(SootheEvent):
    """Research gather done event."""

    type: Literal["soothe.tool.research.gather_done"] = "soothe.tool.research.gather_done"
    query: str = ""
    result_count: int = 0
    sources_used: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchSummarizeEvent(SootheEvent):
    """Research summarize event."""

    type: Literal["soothe.tool.research.summarize"] = "soothe.tool.research.summarize"
    total_summaries: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectEvent(SootheEvent):
    """Research reflect event."""

    type: Literal["soothe.tool.research.reflect"] = "soothe.tool.research.reflect"
    loop: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectionDoneEvent(SootheEvent):
    """Research reflection done event."""

    type: Literal["soothe.tool.research.reflection_done"] = "soothe.tool.research.reflection_done"
    loop: int = 0
    is_sufficient: bool = False
    follow_up_count: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchSynthesizeEvent(SootheEvent):
    """Research synthesize event."""

    type: Literal["soothe.tool.research.synthesize"] = "soothe.tool.research.synthesize"
    topic: str = ""
    total_sources: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchCompletedEvent(SootheEvent):
    """Research completed event."""

    type: Literal["soothe.tool.research.completed"] = "soothe.tool.research.completed"
    answer_length: int = 0

    model_config = ConfigDict(extra="allow")


__all__ = [
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchGatherDoneEvent",
    "ResearchGatherEvent",
    "ResearchQueriesGeneratedEvent",
    "ResearchReflectEvent",
    "ResearchReflectionDoneEvent",
    "ResearchSubQuestionsEvent",
    "ResearchSummarizeEvent",
    "ResearchSynthesizeEvent",
]
