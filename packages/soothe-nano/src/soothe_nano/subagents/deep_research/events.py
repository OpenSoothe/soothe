"""deep_research subagent wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events.catalog import register_event

SUBAGENT_DEEP_RESEARCH_STARTED = "soothe.subagent.deep_research.started"
SUBAGENT_DEEP_RESEARCH_PROGRESS = "soothe.subagent.deep_research.progress"
SUBAGENT_DEEP_RESEARCH_STEP_COMPLETED = "soothe.subagent.deep_research.step.completed"
SUBAGENT_DEEP_RESEARCH_GATHER_SUMMARY = "soothe.subagent.deep_research.gather.summary"
SUBAGENT_DEEP_RESEARCH_CRAWL_SUMMARY = "soothe.subagent.deep_research.crawl.summary"
SUBAGENT_DEEP_RESEARCH_COMPLETED = "soothe.subagent.deep_research.completed"


class DeepResearchStartedEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.started"] = SUBAGENT_DEEP_RESEARCH_STARTED  # type: ignore[assignment]
    topic_preview: str = ""
    effort: str = ""

    model_config = ConfigDict(extra="allow")


class DeepResearchProgressEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.progress"] = SUBAGENT_DEEP_RESEARCH_PROGRESS  # type: ignore[assignment]
    phase: str = ""
    loop_count: int = 0
    total_loops: int = 0
    message: str = ""

    model_config = ConfigDict(extra="allow")


class DeepResearchStepCompletedEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.step.completed"] = (
        SUBAGENT_DEEP_RESEARCH_STEP_COMPLETED  # type: ignore[assignment]
    )
    tool_name: str = ""
    args_preview: str = ""
    status: str = "done"
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


class DeepResearchGatherSummaryEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.gather.summary"] = (
        SUBAGENT_DEEP_RESEARCH_GATHER_SUMMARY  # type: ignore[assignment]
    )
    query_preview: str = ""
    result_count: int = 0
    sources_touched: int = 0

    model_config = ConfigDict(extra="allow")


class DeepResearchCrawlSummaryEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.crawl.summary"] = (
        SUBAGENT_DEEP_RESEARCH_CRAWL_SUMMARY  # type: ignore[assignment]
    )
    urls_crawled: int = 0
    success_count: int = 0

    model_config = ConfigDict(extra="allow")


class DeepResearchCompletedEvent(SootheEvent):
    type: Literal["soothe.subagent.deep_research.completed"] = SUBAGENT_DEEP_RESEARCH_COMPLETED  # type: ignore[assignment]
    duration_ms: int = 0
    scenario: str = ""
    report_length: int = 0
    summary: str = ""
    report_path: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    DeepResearchStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Deep research: {topic_preview}",
)
register_event(
    DeepResearchProgressEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{phase}: {message}",
)
register_event(
    DeepResearchStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {args_preview}",
)
register_event(
    DeepResearchGatherSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Search: {result_count} hits",
)
register_event(
    DeepResearchCrawlSummaryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Crawl: {success_count}/{urls_crawled} URLs",
)
register_event(
    DeepResearchCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{summary}",
)
