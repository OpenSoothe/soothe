"""Research subagent events.

This module defines events for the research subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from dataclasses import field
from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent


class ResearchDispatchedEvent(SootheEvent):
    """Research subagent dispatched event."""

    type: Literal["soothe.capability.research.started"] = "soothe.capability.research.started"
    topic: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchCompletedEvent(SootheEvent):
    """Research completed event."""

    type: Literal["soothe.capability.research.completed"] = "soothe.capability.research.completed"
    duration_ms: int = 0
    answer_length: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchAnalyzeEvent(SootheEvent):
    """Research analyze event."""

    type: Literal["soothe.capability.research.analyzing"] = "soothe.capability.research.analyzing"
    topic: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchSubQuestionsEvent(SootheEvent):
    """Research sub questions event."""

    type: Literal["soothe.capability.research.questions.generating"] = (
        "soothe.capability.research.questions.generating"
    )
    count: int = 0
    sub_questions: list[dict[str, str]] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchQueriesGeneratedEvent(SootheEvent):
    """Research queries generated event."""

    type: Literal["soothe.capability.research.queries.generating"] = (
        "soothe.capability.research.queries.generating"
    )
    queries: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchGatherEvent(SootheEvent):
    """Research gather event."""

    type: Literal["soothe.capability.research.gathering"] = "soothe.capability.research.gathering"
    query: str = ""
    domain: str = ""

    model_config = ConfigDict(extra="allow")


class ResearchGatherDoneEvent(SootheEvent):
    """Research gather done event."""

    type: Literal["soothe.capability.research.gather.completed"] = (
        "soothe.capability.research.gather.completed"
    )
    query: str = ""
    result_count: int = 0
    sources_used: list[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResearchSummarizeEvent(SootheEvent):
    """Research summarize event."""

    type: Literal["soothe.capability.research.summarizing"] = (
        "soothe.capability.research.summarizing"
    )
    total_summaries: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectEvent(SootheEvent):
    """Research reflect event."""

    type: Literal["soothe.capability.research.reflecting"] = "soothe.capability.research.reflecting"
    loop: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchReflectionDoneEvent(SootheEvent):
    """Research reflection done event."""

    type: Literal["soothe.capability.research.reflection.completed"] = (
        "soothe.capability.research.reflection.completed"
    )
    loop: int = 0
    is_sufficient: bool = False
    follow_up_count: int = 0

    model_config = ConfigDict(extra="allow")


class ResearchSynthesizeEvent(SootheEvent):
    """Research synthesize event."""

    type: Literal["soothe.capability.research.synthesizing"] = (
        "soothe.capability.research.synthesizing"
    )
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

    type: Literal["soothe.capability.research.internal_llm.running"] = (
        "soothe.capability.research.internal_llm.running"
    )
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

    type: Literal["soothe.capability.research.judgement.reporting"] = (
        "soothe.capability.research.judgement.reporting"
    )
    judgement: str = ""
    action: str = ""  # "continue" or "complete"
    confidence: float | None = None

    model_config = ConfigDict(extra="allow")


# Register all research events with the global registry
from soothe_sdk.core.verbosity import VerbosityTier  # noqa: E402

from soothe.core.events import register_event  # noqa: E402

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
SUBAGENT_RESEARCH_DISPATCHED = "soothe.capability.research.started"
SUBAGENT_RESEARCH_ANALYZE = "soothe.capability.research.analyzing"
SUBAGENT_RESEARCH_SUB_QUESTIONS = "soothe.capability.research.questions.generating"
SUBAGENT_RESEARCH_QUERIES_GENERATED = "soothe.capability.research.queries.generating"
SUBAGENT_RESEARCH_GATHER = "soothe.capability.research.gathering"
SUBAGENT_RESEARCH_GATHER_DONE = "soothe.capability.research.gather.completed"
SUBAGENT_RESEARCH_SUMMARIZE = "soothe.capability.research.summarizing"
SUBAGENT_RESEARCH_REFLECT = "soothe.capability.research.reflecting"
SUBAGENT_RESEARCH_REFLECTION_DONE = "soothe.capability.research.reflection.completed"
SUBAGENT_RESEARCH_SYNTHESIZE = "soothe.capability.research.synthesizing"
SUBAGENT_RESEARCH_COMPLETED = "soothe.capability.research.completed"
SUBAGENT_RESEARCH_INTERNAL_LLM = "soothe.capability.research.internal_llm.running"
SUBAGENT_RESEARCH_JUDGEMENT = "soothe.capability.research.judgement.reporting"

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
