"""Research subagent events.

This module defines events for the research subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from dataclasses import field
from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.events import SootheEvent


class ResearchDispatchedEvent(SootheEvent):
    """Research subagent dispatched event."""

    type: Literal["soothe.subagent.research.dispatched"] = "soothe.subagent.research.dispatched"
    topic: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchCompletedEvent(SootheEvent):
    """Research completed event."""

    type: Literal["soothe.subagent.research.completed"] = "soothe.subagent.research.completed"
    duration_ms: int = 0
    answer_length: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchAnalyzeEvent(SootheEvent):
    """Research analyze event."""

    type: Literal["soothe.subagent.research.analyze"] = "soothe.subagent.research.analyze"
    topic: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchSubQuestionsEvent(SootheEvent):
    """Research sub questions event."""

    type: Literal["soothe.subagent.research.sub_questions"] = (
        "soothe.subagent.research.sub_questions"
    )
    count: int = 0
    sub_questions: list[dict[str, str]] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchQueriesGeneratedEvent(SootheEvent):
    """Research queries generated event."""

    type: Literal["soothe.subagent.research.queries_generated"] = (
        "soothe.subagent.research.queries_generated"
    )
    queries: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchGatherEvent(SootheEvent):
    """Research gather event."""

    type: Literal["soothe.subagent.research.gather"] = "soothe.subagent.research.gather"
    query: str = ""
    domain: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchGatherDoneEvent(SootheEvent):
    """Research gather done event."""

    type: Literal["soothe.subagent.research.gather_done"] = "soothe.subagent.research.gather_done"
    query: str = ""
    result_count: int = 0
    sources_used: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchSummarizeEvent(SootheEvent):
    """Research summarize event."""

    type: Literal["soothe.subagent.research.summarize"] = "soothe.subagent.research.summarize"
    total_summaries: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectEvent(SootheEvent):
    """Research reflect event."""

    type: Literal["soothe.subagent.research.reflect"] = "soothe.subagent.research.reflect"
    loop: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectionDoneEvent(SootheEvent):
    """Research reflection done event."""

    type: Literal["soothe.subagent.research.reflection_done"] = (
        "soothe.subagent.research.reflection_done"
    )
    loop: int = 0
    is_sufficient: bool = False
    follow_up_count: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchSynthesizeEvent(SootheEvent):
    """Research synthesize event."""

    type: Literal["soothe.subagent.research.synthesize"] = "soothe.subagent.research.synthesize"
    topic: str = ""
    total_sources: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchInternalLLMResponseEvent(SootheEvent):
    """Internal LLM response from research engine - NOT for display.

    This event wraps the raw LLM JSON responses (sub_questions, queries,
    is_sufficient, etc.) that are internal to the research process.
    By emitting them as events with "internal" verbosity, they get properly
    filtered instead of leaking as assistant text.
    """

    type: Literal["soothe.subagent.research.internal_llm"] = "soothe.subagent.research.internal_llm"
    response_type: str = ""  # "analysis", "queries", "reflection"

    model_config = ConfigDict(extra="allow")


class ResearchJudgementEvent(SootheEvent):
    """Research judgement event for displaying LLM decision reasoning.

    IG-089: Shows meaningful judgement info at normal verbosity without
    exposing raw intermediate data. Extracted from reflection responses.

    Attributes:
        judgement: Human-readable summary (e.g., "Need more sources: statistics gap").
        action: Decision taken ("continue" or "complete").
        confidence: Confidence level if available (0.0-1.0).
    """

    type: Literal["soothe.subagent.research.judgement"] = "soothe.subagent.research.judgement"
    judgement: str = ""
    action: str = ""  # "continue" or "complete"
    confidence: float | None = None

    model_config = ConfigDict(extra="allow")


# Register all research events with the global registry
from soothe_sdk.verbosity import VerbosityTier  # noqa: E402

from soothe.core.event_catalog import register_event  # noqa: E402

# Dispatch/Complete events visible at NORMAL (user wants to see start/end)
register_event(
    ResearchDispatchedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Research: {topic}",
)
register_event(
    ResearchCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Completed in {duration_ms}ms",
)

# IG-089: Judgement event visible at NORMAL (shows meaningful progress info)
register_event(
    ResearchJudgementEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{judgement}",
)

# Internal research steps at DETAILED (hidden at normal verbosity)
register_event(
    ResearchAnalyzeEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Analyzing: {topic}",
)
register_event(
    ResearchSubQuestionsEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Identified {count} sub-questions",
)
register_event(
    ResearchQueriesGeneratedEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Generated {queries} queries",
)
register_event(
    ResearchGatherEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Gathering from {domain}: {query}",
)
register_event(
    ResearchGatherDoneEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Gathered {result_count} results",
)
register_event(
    ResearchSummarizeEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Summarizing {total_summaries} results",
)
register_event(
    ResearchReflectEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Reflecting (loop {loop})",
)
register_event(
    ResearchReflectionDoneEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Reflection: sufficient={is_sufficient}",
)
register_event(
    ResearchSynthesizeEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Synthesizing findings",
)

# Internal LLM response - never shown
register_event(
    ResearchInternalLLMResponseEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Internal: {response_type}",
)

# Event type constants for convenient imports
SUBAGENT_RESEARCH_DISPATCHED = "soothe.subagent.research.dispatched"
SUBAGENT_RESEARCH_ANALYZE = "soothe.subagent.research.analyze"
SUBAGENT_RESEARCH_SUB_QUESTIONS = "soothe.subagent.research.sub_questions"
SUBAGENT_RESEARCH_QUERIES_GENERATED = "soothe.subagent.research.queries_generated"
SUBAGENT_RESEARCH_GATHER = "soothe.subagent.research.gather"
SUBAGENT_RESEARCH_GATHER_DONE = "soothe.subagent.research.gather_done"
SUBAGENT_RESEARCH_SUMMARIZE = "soothe.subagent.research.summarize"
SUBAGENT_RESEARCH_REFLECT = "soothe.subagent.research.reflect"
SUBAGENT_RESEARCH_REFLECTION_DONE = "soothe.subagent.research.reflection_done"
SUBAGENT_RESEARCH_SYNTHESIZE = "soothe.subagent.research.synthesize"
SUBAGENT_RESEARCH_COMPLETED = "soothe.subagent.research.completed"
SUBAGENT_RESEARCH_INTERNAL_LLM = "soothe.subagent.research.internal_llm"
SUBAGENT_RESEARCH_JUDGEMENT = "soothe.subagent.research.judgement"

__all__ = [
    "SUBAGENT_RESEARCH_ANALYZE",
    "SUBAGENT_RESEARCH_COMPLETED",
    "SUBAGENT_RESEARCH_DISPATCHED",
    "SUBAGENT_RESEARCH_GATHER",
    "SUBAGENT_RESEARCH_GATHER_DONE",
    "SUBAGENT_RESEARCH_INTERNAL_LLM",
    "SUBAGENT_RESEARCH_JUDGEMENT",
    "SUBAGENT_RESEARCH_QUERIES_GENERATED",
    "SUBAGENT_RESEARCH_REFLECT",
    "SUBAGENT_RESEARCH_REFLECTION_DONE",
    "SUBAGENT_RESEARCH_SUB_QUESTIONS",
    "SUBAGENT_RESEARCH_SUMMARIZE",
    "SUBAGENT_RESEARCH_SYNTHESIZE",
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchDispatchedEvent",
    "ResearchGatherDoneEvent",
    "ResearchGatherEvent",
    "ResearchInternalLLMResponseEvent",
    "ResearchJudgementEvent",
    "ResearchQueriesGeneratedEvent",
    "ResearchReflectEvent",
    "ResearchReflectionDoneEvent",
    "ResearchSubQuestionsEvent",
    "ResearchSummarizeEvent",
    "ResearchSynthesizeEvent",
]
