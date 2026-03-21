"""Typed progress event models, registry, and catalog for soothe.* events.

RFC-0015: All progress events use 4-segment type strings
``soothe.<domain>.<component>.<action>`` with six domains:
lifecycle, protocol, tool, subagent, output, error.

This module is the single source of truth for event type definitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from soothe.core.events import (
    CHECKPOINT_SAVED,
    CHITCHAT_RESPONSE,
    CHITCHAT_STARTED,
    CONTEXT_INGESTED,
    CONTEXT_PROJECTED,
    ERROR,
    FINAL_REPORT,
    GOAL_BATCH_STARTED,
    GOAL_COMPLETED,
    GOAL_CREATED,
    GOAL_DEFERRED,
    GOAL_DIRECTIVES_APPLIED,
    GOAL_FAILED,
    GOAL_REPORT,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    MEMORY_RECALLED,
    MEMORY_STORED,
    PLAN_BATCH_STARTED,
    PLAN_CREATED,
    PLAN_DAG_SNAPSHOT,
    PLAN_ONLY,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    POLICY_CHECKED,
    POLICY_DENIED,
    RECOVERY_RESUMED,
    SUBAGENT_BROWSER_CDP,
    SUBAGENT_BROWSER_STEP,
    SUBAGENT_CLAUDE_RESULT,
    SUBAGENT_CLAUDE_TEXT,
    SUBAGENT_CLAUDE_TOOL_USE,
    SUBAGENT_SKILLIFY_INDEX_FAILED,
    SUBAGENT_SKILLIFY_INDEX_STARTED,
    SUBAGENT_SKILLIFY_INDEX_UNCHANGED,
    SUBAGENT_SKILLIFY_INDEX_UPDATED,
    SUBAGENT_SKILLIFY_INDEXING_PENDING,
    SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED,
    SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY,
    SUBAGENT_SKILLIFY_RETRIEVE_STARTED,
    SUBAGENT_WEAVER_ANALYSIS_COMPLETED,
    SUBAGENT_WEAVER_ANALYSIS_STARTED,
    SUBAGENT_WEAVER_EXECUTE_COMPLETED,
    SUBAGENT_WEAVER_EXECUTE_STARTED,
    SUBAGENT_WEAVER_GENERATE_COMPLETED,
    SUBAGENT_WEAVER_GENERATE_STARTED,
    SUBAGENT_WEAVER_HARMONIZE_COMPLETED,
    SUBAGENT_WEAVER_HARMONIZE_STARTED,
    SUBAGENT_WEAVER_REGISTRY_UPDATED,
    SUBAGENT_WEAVER_REUSE_HIT,
    SUBAGENT_WEAVER_REUSE_MISS,
    SUBAGENT_WEAVER_SKILLIFY_PENDING,
    SUBAGENT_WEAVER_VALIDATE_COMPLETED,
    SUBAGENT_WEAVER_VALIDATE_STARTED,
    THREAD_CREATED,
    THREAD_ENDED,
    THREAD_RESUMED,
    THREAD_SAVED,
    THREAD_STARTED,
    TOOL_RESEARCH_ANALYZE,
    TOOL_RESEARCH_COMPLETED,
    TOOL_RESEARCH_GATHER,
    TOOL_RESEARCH_GATHER_DONE,
    TOOL_RESEARCH_QUERIES_GENERATED,
    TOOL_RESEARCH_REFLECT,
    TOOL_RESEARCH_REFLECTION_DONE,
    TOOL_RESEARCH_SUB_QUESTIONS,
    TOOL_RESEARCH_SUMMARIZE,
    TOOL_RESEARCH_SYNTHESIZE,
    TOOL_WEBSEARCH_CRAWL_COMPLETED,
    TOOL_WEBSEARCH_CRAWL_FAILED,
    TOOL_WEBSEARCH_CRAWL_STARTED,
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
    TOOL_WEBSEARCH_SEARCH_STARTED,
)

if TYPE_CHECKING:
    from soothe.cli.progress_verbosity import ProgressCategory

# ---------------------------------------------------------------------------
# Base models
# ---------------------------------------------------------------------------


class SootheEvent(BaseModel):
    """Base class for all Soothe progress events."""

    type: str

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for wire-format emission."""
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        """Emit this event via the LangGraph stream writer."""
        from soothe.utils.progress import emit_progress

        emit_progress(self.to_dict(), logger)


class LifecycleEvent(SootheEvent):
    """Thread and session lifecycle events."""


class ProtocolEvent(SootheEvent):
    """Core protocol activity events."""


class ToolEvent(SootheEvent):
    """Main agent tool execution events."""

    tool: str


class SubagentEvent(SootheEvent):
    """Subagent activity events."""


class OutputEvent(SootheEvent):
    """Content destined for user display."""


class ErrorEvent(SootheEvent):
    """Error events."""

    error: str


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------


class ThreadCreatedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.created"] = "soothe.lifecycle.thread.created"
    thread_id: str


class ThreadStartedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.started"] = "soothe.lifecycle.thread.started"
    thread_id: str
    protocols: dict[str, Any] = {}


class ThreadResumedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.resumed"] = "soothe.lifecycle.thread.resumed"
    thread_id: str


class ThreadSavedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.saved"] = "soothe.lifecycle.thread.saved"
    thread_id: str


class ThreadEndedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.ended"] = "soothe.lifecycle.thread.ended"
    thread_id: str


class IterationStartedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.iteration.started"] = "soothe.lifecycle.iteration.started"
    iteration: int | str
    goal_id: str = ""
    goal_description: str = ""
    parallel_goals: int = 1


class IterationCompletedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.iteration.completed"] = "soothe.lifecycle.iteration.completed"
    iteration: int | str
    goal_id: str = ""
    outcome: str = ""
    duration_ms: int = 0


class CheckpointSavedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.checkpoint.saved"] = "soothe.lifecycle.checkpoint.saved"
    thread_id: str
    completed_steps: int = 0
    completed_goals: int = 0


class RecoveryResumedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.recovery.resumed"] = "soothe.lifecycle.recovery.resumed"
    thread_id: str
    completed_steps: list[str] = []
    completed_goals: list[str] = []
    mode: str = ""


# ---------------------------------------------------------------------------
# Protocol events
# ---------------------------------------------------------------------------


class ContextProjectedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.context.projected"] = "soothe.protocol.context.projected"
    entries: int = 0
    tokens: int = 0


class ContextIngestedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.context.ingested"] = "soothe.protocol.context.ingested"
    source: str = ""
    content_preview: str = ""


class MemoryRecalledEvent(ProtocolEvent):
    type: Literal["soothe.protocol.memory.recalled"] = "soothe.protocol.memory.recalled"
    count: int = 0
    query: str = ""


class MemoryStoredEvent(ProtocolEvent):
    type: Literal["soothe.protocol.memory.stored"] = "soothe.protocol.memory.stored"
    id: str = ""
    source_thread: str = ""


class PlanCreatedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.created"] = "soothe.protocol.plan.created"
    goal: str = ""
    steps: list[dict[str, Any]] = []


class PlanStepStartedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.step_started"] = "soothe.protocol.plan.step_started"
    step_id: str = ""
    description: str = ""
    depends_on: list[str] = []
    batch_index: int | None = None
    index: int | None = None


class PlanStepCompletedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.step_completed"] = "soothe.protocol.plan.step_completed"
    step_id: str = ""
    success: bool = False
    result_preview: str | None = None
    duration_ms: int | None = None
    index: int | None = None


class PlanStepFailedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.step_failed"] = "soothe.protocol.plan.step_failed"
    step_id: str = ""
    error: str = ""
    blocked_steps: list[str] | None = None
    duration_ms: int | None = None


class PlanBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.batch_started"] = "soothe.protocol.plan.batch_started"
    batch_index: int = 0
    step_ids: list[str] = []
    parallel_count: int = 1


class PlanReflectedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.reflected"] = "soothe.protocol.plan.reflected"
    should_revise: bool = False
    assessment: str = ""


class PlanDagSnapshotEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.dag_snapshot"] = "soothe.protocol.plan.dag_snapshot"
    steps: list[dict[str, Any]] = []


class PlanOnlyEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.plan_only"] = "soothe.protocol.plan.plan_only"
    thread_id: str = ""
    goal: str = ""
    step_count: int = 0


class PolicyCheckedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.policy.checked"] = "soothe.protocol.policy.checked"
    action: str = ""
    verdict: str = ""
    profile: str | None = None


class PolicyDeniedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.policy.denied"] = "soothe.protocol.policy.denied"
    action: str = ""
    reason: str = ""
    profile: str | None = None


class GoalCreatedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.created"] = "soothe.protocol.goal.created"
    goal_id: str = ""
    description: str = ""
    priority: int | str = ""


class GoalCompletedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.completed"] = "soothe.protocol.goal.completed"
    goal_id: str = ""


class GoalFailedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.failed"] = "soothe.protocol.goal.failed"
    goal_id: str = ""
    error: str = ""
    retry_count: int = 0


class GoalBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.batch_started"] = "soothe.protocol.goal.batch_started"
    goal_ids: list[str] = []
    parallel_count: int = 1


class GoalReportEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.report"] = "soothe.protocol.goal.report"
    goal_id: str = ""
    step_count: int = 0
    completed: int = 0
    failed: int = 0
    summary: str = ""


class GoalDirectivesAppliedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.directives_applied"] = "soothe.protocol.goal.directives_applied"
    goal_id: str = ""
    directives_count: int = 0
    changes: list[Any] = []


class GoalDeferredEvent(ProtocolEvent):
    type: Literal["soothe.protocol.goal.deferred"] = "soothe.protocol.goal.deferred"
    goal_id: str = ""
    reason: str = ""
    plan_preserved: bool = False


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------


class ToolStartedEvent(ToolEvent):
    tool: str
    args: str = ""
    kwargs: str = ""


class ToolCompletedEvent(ToolEvent):
    tool: str
    result_preview: str = ""


class ToolFailedEvent(ToolEvent):
    tool: str
    error: str = ""


def make_tool_started(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-started event dict.

    Args:
        tool_name: Internal tool name (e.g. ``search_web``).
        tool_group: User-facing tool group (e.g. ``websearch``).
            When provided the type uses ``soothe.tool.<group>.<tool>_started``;
            otherwise falls back to ``soothe.tool.<tool>.started``.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_started" if tool_group else f"soothe.tool.{tool_name}.started"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


def make_tool_completed(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-completed event dict.

    Args:
        tool_name: Internal tool name.
        tool_group: User-facing tool group.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_completed" if tool_group else f"soothe.tool.{tool_name}.completed"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


def make_tool_failed(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-failed event dict.

    Args:
        tool_name: Internal tool name.
        tool_group: User-facing tool group.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_failed" if tool_group else f"soothe.tool.{tool_name}.failed"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


# ---------------------------------------------------------------------------
# Subagent events — Browser
# ---------------------------------------------------------------------------


class BrowserStepEvent(SubagentEvent):
    type: Literal["soothe.subagent.browser.step"] = "soothe.subagent.browser.step"
    step: int | str = ""
    url: str = ""
    action: str = ""
    title: str = ""
    is_done: bool = False


class BrowserCdpEvent(SubagentEvent):
    type: Literal["soothe.subagent.browser.cdp"] = "soothe.subagent.browser.cdp"
    status: str = ""
    cdp_url: str | None = None


# ---------------------------------------------------------------------------
# Subagent events — Claude
# ---------------------------------------------------------------------------


class ClaudeTextEvent(SubagentEvent):
    type: Literal["soothe.subagent.claude.text"] = "soothe.subagent.claude.text"
    text: str = ""


class ClaudeToolUseEvent(SubagentEvent):
    type: Literal["soothe.subagent.claude.tool_use"] = "soothe.subagent.claude.tool_use"
    tool: str = ""


class ClaudeResultEvent(SubagentEvent):
    type: Literal["soothe.subagent.claude.result"] = "soothe.subagent.claude.result"
    cost_usd: float = 0.0
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Subagent events — Skillify
# ---------------------------------------------------------------------------


class SkillifyIndexingPendingEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.indexing_pending"] = "soothe.subagent.skillify.indexing_pending"
    query: str = ""


class SkillifyRetrieveStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_started"] = "soothe.subagent.skillify.retrieve_started"
    query: str = ""


class SkillifyRetrieveCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_completed"] = "soothe.subagent.skillify.retrieve_completed"
    query: str = ""
    result_count: int = 0
    top_score: float = 0.0


class SkillifyRetrieveNotReadyEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.retrieve_not_ready"] = "soothe.subagent.skillify.retrieve_not_ready"
    message: str = ""


class SkillifyIndexStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_started"] = "soothe.subagent.skillify.index_started"
    collection: str = ""


class SkillifyIndexUpdatedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_updated"] = "soothe.subagent.skillify.index_updated"
    new: int = 0
    changed: int = 0
    deleted: int = 0
    total: int = 0


class SkillifyIndexUnchangedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_unchanged"] = "soothe.subagent.skillify.index_unchanged"
    total: int = 0


class SkillifyIndexFailedEvent(SubagentEvent):
    type: Literal["soothe.subagent.skillify.index_failed"] = "soothe.subagent.skillify.index_failed"


# ---------------------------------------------------------------------------
# Subagent events — Weaver
# ---------------------------------------------------------------------------


class WeaverAnalysisStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.analysis_started"] = "soothe.subagent.weaver.analysis_started"
    task_preview: str = ""


class WeaverAnalysisCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.analysis_completed"] = "soothe.subagent.weaver.analysis_completed"
    capabilities: list[Any] = []
    constraints: list[Any] = []


class WeaverReuseHitEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.reuse_hit"] = "soothe.subagent.weaver.reuse_hit"
    agent_name: str = ""
    confidence: float = 0.0


class WeaverReuseMissEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.reuse_miss"] = "soothe.subagent.weaver.reuse_miss"
    best_confidence: float = 0.0


class WeaverSkillifyPendingEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.skillify_pending"] = "soothe.subagent.weaver.skillify_pending"


class WeaverHarmonizeStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.harmonize_started"] = "soothe.subagent.weaver.harmonize_started"
    skill_count: int = 0


class WeaverHarmonizeCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.harmonize_completed"] = "soothe.subagent.weaver.harmonize_completed"
    retained: int = 0
    dropped: int = 0
    bridge_length: int = 0


class WeaverGenerateStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.generate_started"] = "soothe.subagent.weaver.generate_started"
    agent_name: str = ""


class WeaverGenerateCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.generate_completed"] = "soothe.subagent.weaver.generate_completed"
    agent_name: str = ""
    path: str = ""


class WeaverValidateStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.validate_started"] = "soothe.subagent.weaver.validate_started"
    agent_name: str = ""


class WeaverValidateCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.validate_completed"] = "soothe.subagent.weaver.validate_completed"
    agent_name: str = ""


class WeaverRegistryUpdatedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.registry_updated"] = "soothe.subagent.weaver.registry_updated"
    agent_name: str = ""
    version: str = ""


class WeaverExecuteStartedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.execute_started"] = "soothe.subagent.weaver.execute_started"
    agent_name: str = ""
    task_preview: str = ""


class WeaverExecuteCompletedEvent(SubagentEvent):
    type: Literal["soothe.subagent.weaver.execute_completed"] = "soothe.subagent.weaver.execute_completed"
    agent_name: str = ""
    result_length: int = 0


# ---------------------------------------------------------------------------
# Tool events — Research (InquiryEngine phases, exposed as the "research" tool)
# ---------------------------------------------------------------------------


class ResearchAnalyzeEvent(SootheEvent):
    type: Literal["soothe.tool.research.analyze"] = "soothe.tool.research.analyze"
    topic: str = ""


class ResearchSubQuestionsEvent(SootheEvent):
    type: Literal["soothe.tool.research.sub_questions"] = "soothe.tool.research.sub_questions"
    count: int = 0


class ResearchQueriesGeneratedEvent(SootheEvent):
    type: Literal["soothe.tool.research.queries_generated"] = "soothe.tool.research.queries_generated"
    queries: list[str] = []


class ResearchGatherEvent(SootheEvent):
    type: Literal["soothe.tool.research.gather"] = "soothe.tool.research.gather"
    query: str = ""
    domain: str = ""


class ResearchGatherDoneEvent(SootheEvent):
    type: Literal["soothe.tool.research.gather_done"] = "soothe.tool.research.gather_done"
    query: str = ""
    result_count: int = 0
    sources_used: list[str] = []


class ResearchSummarizeEvent(SootheEvent):
    type: Literal["soothe.tool.research.summarize"] = "soothe.tool.research.summarize"
    total_summaries: int = 0


class ResearchReflectEvent(SootheEvent):
    type: Literal["soothe.tool.research.reflect"] = "soothe.tool.research.reflect"
    loop: int = 0


class ResearchReflectionDoneEvent(SootheEvent):
    type: Literal["soothe.tool.research.reflection_done"] = "soothe.tool.research.reflection_done"
    loop: int = 0
    is_sufficient: bool = False
    follow_up_count: int = 0


class ResearchSynthesizeEvent(SootheEvent):
    type: Literal["soothe.tool.research.synthesize"] = "soothe.tool.research.synthesize"
    topic: str = ""
    total_sources: int = 0


class ResearchCompletedEvent(SootheEvent):
    type: Literal["soothe.tool.research.completed"] = "soothe.tool.research.completed"
    answer_length: int = 0


# ---------------------------------------------------------------------------
# Subagent tool events (generic for any subagent)
# ---------------------------------------------------------------------------


def make_subagent_tool_started(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-started event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_started", **extra}


def make_subagent_tool_completed(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-completed event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_completed", **extra}


def make_subagent_tool_failed(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-failed event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_failed", **extra}


# ---------------------------------------------------------------------------
# Output events
# ---------------------------------------------------------------------------


class ChitchatStartedEvent(OutputEvent):
    type: Literal["soothe.output.chitchat.started"] = "soothe.output.chitchat.started"
    query: str = ""


class ChitchatResponseEvent(OutputEvent):
    type: Literal["soothe.output.chitchat.response"] = "soothe.output.chitchat.response"
    content: str = ""


class FinalReportEvent(OutputEvent):
    type: Literal["soothe.output.autonomous.final_report"] = "soothe.output.autonomous.final_report"
    goal_id: str = ""
    description: str = ""
    status: str = ""
    summary: str = ""


# ---------------------------------------------------------------------------
# Error events
# ---------------------------------------------------------------------------


class GeneralErrorEvent(ErrorEvent):
    type: Literal["soothe.error.general"] = "soothe.error.general"
    error: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EventHandler = Any  # Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class EventMeta:
    """Metadata for a registered event type."""

    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: ProgressCategory
    summary_template: str = ""


_DOMAIN_DEFAULT_VERBOSITY: dict[str, ProgressCategory] = {
    "lifecycle": "protocol",
    "protocol": "protocol",
    "tool": "tool_activity",
    "subagent": "subagent_custom",
    "output": "assistant_text",
    "error": "error",
}


@dataclass
class EventRegistry:
    """Central registry for all Soothe event types.

    Provides O(1) lookup by event type string, structural domain
    classification, verbosity resolution, and handler dispatch.
    """

    _by_type: dict[str, EventMeta] = field(default_factory=dict)
    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def register(self, meta: EventMeta) -> None:
        """Register an event type with its metadata."""
        self._by_type[meta.type_string] = meta

    def get_meta(self, event_type: str) -> EventMeta | None:
        """Look up metadata for an event type string."""
        return self._by_type.get(event_type)

    def classify(self, event_type: str) -> str:
        """Return the domain from an event type string via ``split('.')[1]``."""
        segments = event_type.split(".")
        _min_segments = 2
        return segments[1] if len(segments) >= _min_segments else "unknown"

    def get_verbosity(self, event_type: str) -> str:
        """Return the verbosity category for an event type."""
        meta = self._by_type.get(event_type)
        if meta:
            return meta.verbosity
        domain = self.classify(event_type)
        return _DOMAIN_DEFAULT_VERBOSITY.get(domain, "debug")

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type (or ``*`` for fallback)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: dict[str, Any]) -> None:
        """Dispatch an event dict to registered handlers."""
        etype = event.get("type", "")
        handlers = self._handlers.get(etype)
        if handlers:
            for h in handlers:
                h(event)
        elif "*" in self._handlers:
            for h in self._handlers["*"]:
                h(event)


REGISTRY = EventRegistry()


def _reg(
    type_string: str,
    model: type[SootheEvent],
    verbosity: ProgressCategory | None = None,
    summary_template: str = "",
) -> None:
    parts = type_string.split(".")
    domain = parts[1] if len(parts) >= 2 else "unknown"
    component = parts[2] if len(parts) >= 3 else ""
    action = parts[3] if len(parts) >= 4 else ""
    v = verbosity or _DOMAIN_DEFAULT_VERBOSITY.get(domain, "debug")
    REGISTRY.register(
        EventMeta(
            type_string=type_string,
            model=model,
            domain=domain,
            component=component,
            action=action,
            verbosity=v,
            summary_template=summary_template,
        )
    )


# -- Lifecycle ---------------------------------------------------------------
_reg(THREAD_CREATED, ThreadCreatedEvent, summary_template="Thread {thread_id} created")
_reg(THREAD_STARTED, ThreadStartedEvent, summary_template="thread={thread_id}")
_reg(THREAD_RESUMED, ThreadResumedEvent, summary_template="Resumed thread: {thread_id}")
_reg(THREAD_SAVED, ThreadSavedEvent, summary_template="Saved thread: {thread_id}")
_reg(THREAD_ENDED, ThreadEndedEvent, summary_template="thread={thread_id}")
_reg(
    ITERATION_STARTED,
    IterationStartedEvent,
    summary_template="iteration {iteration}: {goal_description}",
)
_reg(
    ITERATION_COMPLETED,
    IterationCompletedEvent,
    summary_template="iteration {iteration}: {outcome} ({duration_ms}ms)",
)
_reg(
    CHECKPOINT_SAVED,
    CheckpointSavedEvent,
    summary_template="Checkpoint saved: {completed_steps} steps, {completed_goals} goals",
)
_reg(
    RECOVERY_RESUMED,
    RecoveryResumedEvent,
    summary_template="Recovery resumed: mode={mode}",
)

# -- Protocol: context -------------------------------------------------------
_reg(CONTEXT_PROJECTED, ContextProjectedEvent, summary_template="{entries} entries, {tokens} tokens")
_reg(CONTEXT_INGESTED, ContextIngestedEvent, summary_template="Ingested from {source}")

# -- Protocol: memory --------------------------------------------------------
_reg(MEMORY_RECALLED, MemoryRecalledEvent, summary_template="{count} items recalled")
_reg(MEMORY_STORED, MemoryStoredEvent, summary_template="Stored memory: {id}")

# -- Protocol: plan ----------------------------------------------------------
_reg(PLAN_CREATED, PlanCreatedEvent, summary_template="Plan: {goal}")
_reg(PLAN_STEP_STARTED, PlanStepStartedEvent, summary_template="Step {step_id}: {description}")
_reg(PLAN_STEP_COMPLETED, PlanStepCompletedEvent, summary_template="Step {step_id}: done")
_reg(PLAN_STEP_FAILED, PlanStepFailedEvent, summary_template="Step {step_id}: FAILED - {error}")
_reg(PLAN_BATCH_STARTED, PlanBatchStartedEvent, summary_template="Batch: {parallel_count} steps in parallel")
_reg(PLAN_REFLECTED, PlanReflectedEvent, summary_template="Reflected: {assessment}")
_reg(PLAN_DAG_SNAPSHOT, PlanDagSnapshotEvent, verbosity="debug")
_reg(PLAN_ONLY, PlanOnlyEvent, summary_template="Plan only: {step_count} steps")

# -- Protocol: policy --------------------------------------------------------
_reg(POLICY_CHECKED, PolicyCheckedEvent, summary_template="Policy: {verdict}")
_reg(POLICY_DENIED, PolicyDeniedEvent, summary_template="Denied: {reason}")

# -- Protocol: goal ----------------------------------------------------------
_reg(GOAL_CREATED, GoalCreatedEvent, summary_template="Goal: {description} (priority={priority})")
_reg(GOAL_COMPLETED, GoalCompletedEvent, summary_template="Goal {goal_id} completed")
_reg(GOAL_FAILED, GoalFailedEvent, summary_template="Goal {goal_id} failed (retry {retry_count})")
_reg(GOAL_BATCH_STARTED, GoalBatchStartedEvent, summary_template="Goals: {parallel_count} running in parallel")
_reg(GOAL_REPORT, GoalReportEvent, summary_template="[goal] {goal_id}: {completed}/{step_count} steps")
_reg(
    GOAL_DIRECTIVES_APPLIED,
    GoalDirectivesAppliedEvent,
    summary_template="Directives applied: {directives_count} changes",
)
_reg(GOAL_DEFERRED, GoalDeferredEvent, summary_template="Goal {goal_id} deferred: {reason}")

# -- Tool: websearch group (search + crawl) --------------------------
_reg(TOOL_WEBSEARCH_SEARCH_STARTED, ToolStartedEvent, summary_template="Searching: {query}")
_reg(TOOL_WEBSEARCH_SEARCH_COMPLETED, ToolCompletedEvent, summary_template="Found {result_count} results")
_reg(TOOL_WEBSEARCH_SEARCH_FAILED, ToolFailedEvent, summary_template="Search failed: {error}")
_reg(TOOL_WEBSEARCH_CRAWL_STARTED, ToolStartedEvent, summary_template="Crawling: {url}")
_reg(TOOL_WEBSEARCH_CRAWL_COMPLETED, ToolCompletedEvent, summary_template="Crawl complete: {content_length} bytes")
_reg(TOOL_WEBSEARCH_CRAWL_FAILED, ToolFailedEvent, summary_template="Crawl failed: {error}")

# -- Subagent: browser -------------------------------------------------------
_reg(SUBAGENT_BROWSER_STEP, BrowserStepEvent, verbosity="subagent_progress", summary_template="Step {step}")
_reg(SUBAGENT_BROWSER_CDP, BrowserCdpEvent, verbosity="subagent_progress", summary_template="Browser CDP: {status}")

# -- Subagent: claude --------------------------------------------------------
_reg(SUBAGENT_CLAUDE_TEXT, ClaudeTextEvent, verbosity="protocol", summary_template="Text: {text}")
_reg(SUBAGENT_CLAUDE_TOOL_USE, ClaudeToolUseEvent, summary_template="Tool: {tool}")
_reg(
    SUBAGENT_CLAUDE_RESULT,
    ClaudeResultEvent,
    verbosity="protocol",
    summary_template="Done (${cost_usd}, {duration_ms}ms)",
)

# -- Subagent: skillify ------------------------------------------------------
_reg(SUBAGENT_SKILLIFY_INDEXING_PENDING, SkillifyIndexingPendingEvent)
_reg(SUBAGENT_SKILLIFY_RETRIEVE_STARTED, SkillifyRetrieveStartedEvent)
_reg(SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED, SkillifyRetrieveCompletedEvent)
_reg(SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY, SkillifyRetrieveNotReadyEvent)
_reg(SUBAGENT_SKILLIFY_INDEX_STARTED, SkillifyIndexStartedEvent)
_reg(SUBAGENT_SKILLIFY_INDEX_UPDATED, SkillifyIndexUpdatedEvent)
_reg(SUBAGENT_SKILLIFY_INDEX_UNCHANGED, SkillifyIndexUnchangedEvent)
_reg(SUBAGENT_SKILLIFY_INDEX_FAILED, SkillifyIndexFailedEvent)

# -- Subagent: weaver --------------------------------------------------------
_reg(SUBAGENT_WEAVER_ANALYSIS_STARTED, WeaverAnalysisStartedEvent)
_reg(SUBAGENT_WEAVER_ANALYSIS_COMPLETED, WeaverAnalysisCompletedEvent)
_reg(SUBAGENT_WEAVER_REUSE_HIT, WeaverReuseHitEvent)
_reg(SUBAGENT_WEAVER_REUSE_MISS, WeaverReuseMissEvent)
_reg(SUBAGENT_WEAVER_SKILLIFY_PENDING, WeaverSkillifyPendingEvent)
_reg(SUBAGENT_WEAVER_HARMONIZE_STARTED, WeaverHarmonizeStartedEvent)
_reg(SUBAGENT_WEAVER_HARMONIZE_COMPLETED, WeaverHarmonizeCompletedEvent)
_reg(SUBAGENT_WEAVER_GENERATE_STARTED, WeaverGenerateStartedEvent)
_reg(SUBAGENT_WEAVER_GENERATE_COMPLETED, WeaverGenerateCompletedEvent)
_reg(SUBAGENT_WEAVER_VALIDATE_STARTED, WeaverValidateStartedEvent)
_reg(SUBAGENT_WEAVER_VALIDATE_COMPLETED, WeaverValidateCompletedEvent)
_reg(SUBAGENT_WEAVER_REGISTRY_UPDATED, WeaverRegistryUpdatedEvent)
_reg(SUBAGENT_WEAVER_EXECUTE_STARTED, WeaverExecuteStartedEvent)
_reg(SUBAGENT_WEAVER_EXECUTE_COMPLETED, WeaverExecuteCompletedEvent)

# -- Tool: research group (InquiryEngine phases) -----------------------------
_reg(TOOL_RESEARCH_ANALYZE, ResearchAnalyzeEvent, verbosity="protocol", summary_template="Analyzing: {topic}")
_reg(TOOL_RESEARCH_SUB_QUESTIONS, ResearchSubQuestionsEvent, summary_template="Identified {count} sub-questions")
_reg(
    TOOL_RESEARCH_QUERIES_GENERATED,
    ResearchQueriesGeneratedEvent,
    summary_template="Generated {queries} queries",
)
_reg(TOOL_RESEARCH_GATHER, ResearchGatherEvent, summary_template="Gathering from {domain}: {query}")
_reg(
    TOOL_RESEARCH_GATHER_DONE,
    ResearchGatherDoneEvent,
    summary_template="Gathered {result_count} results",
)
_reg(TOOL_RESEARCH_SUMMARIZE, ResearchSummarizeEvent, summary_template="Summarizing {total_summaries} results")
_reg(TOOL_RESEARCH_REFLECT, ResearchReflectEvent, summary_template="Reflecting (loop {loop})")
_reg(
    TOOL_RESEARCH_REFLECTION_DONE,
    ResearchReflectionDoneEvent,
    summary_template="Reflection: sufficient={is_sufficient}",
)
_reg(
    TOOL_RESEARCH_SYNTHESIZE,
    ResearchSynthesizeEvent,
    verbosity="protocol",
    summary_template="Synthesizing findings",
)
_reg(
    TOOL_RESEARCH_COMPLETED,
    ResearchCompletedEvent,
    verbosity="protocol",
    summary_template="Research completed ({answer_length} chars)",
)

# -- Output ------------------------------------------------------------------
_reg(CHITCHAT_STARTED, ChitchatStartedEvent, summary_template="Chitchat: {query}")
_reg(CHITCHAT_RESPONSE, ChitchatResponseEvent, verbosity="assistant_text")
_reg(FINAL_REPORT, FinalReportEvent, verbosity="assistant_text")

# -- Error -------------------------------------------------------------------
_reg(ERROR, GeneralErrorEvent, verbosity="error", summary_template="{error}")
