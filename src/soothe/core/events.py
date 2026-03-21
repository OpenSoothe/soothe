"""Unified event type definitions for soothe.* events.

This module provides event type constants derived from the event catalog,
ensuring a single source of truth. All event types follow RFC-0015's 4-segment
naming convention: ``soothe.<domain>.<component>.<action>``.

**Single Source of Truth:**
All event type strings are defined once in ``soothe.core.event_catalog`` and
re-exported here as constants for convenient use throughout the codebase.

**Usage:**

For type-safe event emission (recommended):
    from soothe.core.event_catalog import ThreadCreatedEvent, PlanStepStartedEvent
    yield _custom(ThreadCreatedEvent(thread_id=tid).to_dict())
    yield _custom(PlanStepStartedEvent(step_id=sid, ...).to_dict())

For event type string constants:
    from soothe.core.events import THREAD_CREATED, PLAN_STEP_STARTED
    # Use constants for comparisons, routing, etc.
    if event_type == THREAD_CREATED:
        ...

RFC-0015: All event types use 4-segment naming
``soothe.<domain>.<component>.<action>``.
"""

from __future__ import annotations

from typing import Any

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

STREAM_CHUNK_LEN = 3
MSG_PAIR_LEN = 2

# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------
THREAD_CREATED = "soothe.lifecycle.thread.created"
THREAD_STARTED = "soothe.lifecycle.thread.started"
THREAD_RESUMED = "soothe.lifecycle.thread.resumed"
THREAD_SAVED = "soothe.lifecycle.thread.saved"
THREAD_ENDED = "soothe.lifecycle.thread.ended"
ITERATION_STARTED = "soothe.lifecycle.iteration.started"
ITERATION_COMPLETED = "soothe.lifecycle.iteration.completed"
CHECKPOINT_SAVED = "soothe.lifecycle.checkpoint.saved"
RECOVERY_RESUMED = "soothe.lifecycle.recovery.resumed"

# ---------------------------------------------------------------------------
# Protocol events
# ---------------------------------------------------------------------------
CONTEXT_PROJECTED = "soothe.protocol.context.projected"
CONTEXT_INGESTED = "soothe.protocol.context.ingested"
MEMORY_RECALLED = "soothe.protocol.memory.recalled"
MEMORY_STORED = "soothe.protocol.memory.stored"
PLAN_CREATED = "soothe.protocol.plan.created"
PLAN_STEP_STARTED = "soothe.protocol.plan.step_started"
PLAN_STEP_COMPLETED = "soothe.protocol.plan.step_completed"
PLAN_STEP_FAILED = "soothe.protocol.plan.step_failed"
PLAN_BATCH_STARTED = "soothe.protocol.plan.batch_started"
PLAN_REFLECTED = "soothe.protocol.plan.reflected"
PLAN_DAG_SNAPSHOT = "soothe.protocol.plan.dag_snapshot"
PLAN_ONLY = "soothe.protocol.plan.plan_only"
POLICY_CHECKED = "soothe.protocol.policy.checked"
POLICY_DENIED = "soothe.protocol.policy.denied"
GOAL_CREATED = "soothe.protocol.goal.created"
GOAL_COMPLETED = "soothe.protocol.goal.completed"
GOAL_FAILED = "soothe.protocol.goal.failed"
GOAL_BATCH_STARTED = "soothe.protocol.goal.batch_started"
GOAL_REPORT = "soothe.protocol.goal.report"
GOAL_DIRECTIVES_APPLIED = "soothe.protocol.goal.directives_applied"
GOAL_DEFERRED = "soothe.protocol.goal.deferred"

# ---------------------------------------------------------------------------
# Output events
# ---------------------------------------------------------------------------
CHITCHAT_STARTED = "soothe.output.chitchat.started"
CHITCHAT_RESPONSE = "soothe.output.chitchat.response"
FINAL_REPORT = "soothe.output.autonomous.final_report"

# ---------------------------------------------------------------------------
# Tool events — websearch group (internally uses wizsearch/serper backends)
# ---------------------------------------------------------------------------
TOOL_WEBSEARCH_SEARCH_STARTED = "soothe.tool.websearch.search_started"
TOOL_WEBSEARCH_SEARCH_COMPLETED = "soothe.tool.websearch.search_completed"
TOOL_WEBSEARCH_SEARCH_FAILED = "soothe.tool.websearch.search_failed"
TOOL_WEBSEARCH_CRAWL_STARTED = "soothe.tool.websearch.crawl_started"
TOOL_WEBSEARCH_CRAWL_COMPLETED = "soothe.tool.websearch.crawl_completed"
TOOL_WEBSEARCH_CRAWL_FAILED = "soothe.tool.websearch.crawl_failed"

# ---------------------------------------------------------------------------
# Tool events — research (InquiryEngine phases)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Subagent events — Browser
# ---------------------------------------------------------------------------
SUBAGENT_BROWSER_STEP = "soothe.subagent.browser.step"
SUBAGENT_BROWSER_CDP = "soothe.subagent.browser.cdp"

# ---------------------------------------------------------------------------
# Subagent events — Claude
# ---------------------------------------------------------------------------
SUBAGENT_CLAUDE_TEXT = "soothe.subagent.claude.text"
SUBAGENT_CLAUDE_TOOL_USE = "soothe.subagent.claude.tool_use"
SUBAGENT_CLAUDE_RESULT = "soothe.subagent.claude.result"

# ---------------------------------------------------------------------------
# Subagent events — Skillify
# ---------------------------------------------------------------------------
SUBAGENT_SKILLIFY_INDEXING_PENDING = "soothe.subagent.skillify.indexing_pending"
SUBAGENT_SKILLIFY_RETRIEVE_STARTED = "soothe.subagent.skillify.retrieve_started"
SUBAGENT_SKILLIFY_RETRIEVE_COMPLETED = "soothe.subagent.skillify.retrieve_completed"
SUBAGENT_SKILLIFY_RETRIEVE_NOT_READY = "soothe.subagent.skillify.retrieve_not_ready"
SUBAGENT_SKILLIFY_INDEX_STARTED = "soothe.subagent.skillify.index_started"
SUBAGENT_SKILLIFY_INDEX_UPDATED = "soothe.subagent.skillify.index_updated"
SUBAGENT_SKILLIFY_INDEX_UNCHANGED = "soothe.subagent.skillify.index_unchanged"
SUBAGENT_SKILLIFY_INDEX_FAILED = "soothe.subagent.skillify.index_failed"

# ---------------------------------------------------------------------------
# Subagent events — Weaver
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Error events
# ---------------------------------------------------------------------------
ERROR = "soothe.error.general"


def custom_event(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk.

    Args:
        data: Event data dict with 'type' key.

    Returns:
        Stream chunk in deepagents-canonical format.
    """
    return ((), "custom", data)
