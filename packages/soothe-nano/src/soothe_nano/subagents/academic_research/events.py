"""academic_research subagent wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events.catalog import register_event

SUBAGENT_ACADEMIC_RESEARCH_STARTED = "soothe.subagent.academic_research.started"
SUBAGENT_ACADEMIC_RESEARCH_PROGRESS = "soothe.subagent.academic_research.progress"
SUBAGENT_ACADEMIC_RESEARCH_STEP_COMPLETED = "soothe.subagent.academic_research.step.completed"
SUBAGENT_ACADEMIC_RESEARCH_GATHER_SUMMARY = "soothe.subagent.academic_research.gather.summary"
SUBAGENT_ACADEMIC_RESEARCH_CRAWL_SUMMARY = "soothe.subagent.academic_research.crawl.summary"
SUBAGENT_ACADEMIC_RESEARCH_COMPLETED = "soothe.subagent.academic_research.completed"


class AcademicResearchStartedEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.started"] = (  # type: ignore[assignment]
        SUBAGENT_ACADEMIC_RESEARCH_STARTED
    )
    topic_preview: str = ""
    effort: str = ""

    model_config = ConfigDict(extra="allow")


class AcademicResearchProgressEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.progress"] = (  # type: ignore[assignment]
        SUBAGENT_ACADEMIC_RESEARCH_PROGRESS
    )
    phase: str = ""
    loop_count: int = 0
    total_loops: int = 0
    message: str = ""

    model_config = ConfigDict(extra="allow")


class AcademicResearchStepCompletedEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.step.completed"] = (
        SUBAGENT_ACADEMIC_RESEARCH_STEP_COMPLETED  # type: ignore[assignment]
    )
    tool_name: str = ""
    args_preview: str = ""
    status: str = "done"
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


class AcademicResearchGatherSummaryEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.gather.summary"] = (
        SUBAGENT_ACADEMIC_RESEARCH_GATHER_SUMMARY  # type: ignore[assignment]
    )
    query_preview: str = ""
    result_count: int = 0
    sources_touched: int = 0

    model_config = ConfigDict(extra="allow")


class AcademicResearchCrawlSummaryEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.crawl.summary"] = (
        SUBAGENT_ACADEMIC_RESEARCH_CRAWL_SUMMARY  # type: ignore[assignment]
    )
    urls_crawled: int = 0
    success_count: int = 0

    model_config = ConfigDict(extra="allow")


class AcademicResearchCompletedEvent(SootheEvent):
    type: Literal["soothe.subagent.academic_research.completed"] = (  # type: ignore[assignment]
        SUBAGENT_ACADEMIC_RESEARCH_COMPLETED
    )
    duration_ms: int = 0
    scenario: str = ""
    report_length: int = 0
    summary: str = ""
    report_path: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    AcademicResearchStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Academic research: {topic_preview}",
)
register_event(
    AcademicResearchProgressEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{phase}: {message}",
)
register_event(
    AcademicResearchStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {args_preview}",
)
register_event(
    AcademicResearchGatherSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Search: {result_count} hits",
)
register_event(
    AcademicResearchCrawlSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Crawl: {success_count}/{urls_crawled} URLs",
)
register_event(
    AcademicResearchCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{summary}",
)
