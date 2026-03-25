"""Research tool events.

This module defines events for the research tool.
Events are self-registered at module load time.
"""

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


# Register all research events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(ResearchAnalyzeEvent, summary_template="Analyzing: {topic}")
register_event(ResearchSubQuestionsEvent, summary_template="Identified {count} sub-questions")
register_event(ResearchQueriesGeneratedEvent, summary_template="Generated {queries} queries")
register_event(ResearchGatherEvent, summary_template="Gathering from {domain}: {query}")
register_event(ResearchGatherDoneEvent, summary_template="Gathered {result_count} results")
register_event(ResearchSummarizeEvent, summary_template="Summarizing {total_summaries} results")
register_event(ResearchReflectEvent, summary_template="Reflecting (loop {loop})")
register_event(
    ResearchReflectionDoneEvent,
    summary_template="Reflection: sufficient={is_sufficient}",
)
register_event(ResearchSynthesizeEvent, summary_template="Synthesizing findings")
register_event(
    ResearchCompletedEvent,
    summary_template="Research completed ({answer_length} chars)",
)

# Event type constants for convenient imports
TOOL_RESEARCH_ANALYZE = "soothe.tool.research.analyze"
TOOL_RESEARCH_SUB_QUESTIONS = "soothe.tool.research.sub_questions"
TOOL_RESEARCH_QUERIES_GENERATED = "soothe.tool.research.queries_generated"
TOOL_RESEARCH_GATHER = "soothe.tool.research.gather"
TOOL_RESEARCH_GATHER_DONE = "soothe.tool.research.gather_done"
TOOL_RESEARCH_SUMMARIZE = "soothe.tool.research.summarize"
TOOL_RESEARCH_REFLECT = "soothe.tool.research.reflect"
TOOL_RESEARCH_REFLECTION_DONE = "soothe.tool.research.reflection_done"
TOOL_RESEARCH_SYNTHESIZE = "soothe.tool.research.synthesize"
TOOL_RESEARCH_COMPLETED = "soothe.tool.research.completed"

__all__ = [
    "TOOL_RESEARCH_ANALYZE",
    "TOOL_RESEARCH_COMPLETED",
    "TOOL_RESEARCH_GATHER",
    "TOOL_RESEARCH_GATHER_DONE",
    "TOOL_RESEARCH_QUERIES_GENERATED",
    "TOOL_RESEARCH_REFLECT",
    "TOOL_RESEARCH_REFLECTION_DONE",
    "TOOL_RESEARCH_SUB_QUESTIONS",
    "TOOL_RESEARCH_SUMMARIZE",
    "TOOL_RESEARCH_SYNTHESIZE",
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
