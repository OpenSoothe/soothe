"""Registry-based event renderer for headless CLI output.

This module implements RFC-0015's registry-based dispatch to replace the old
O(n) if-elif chains with O(1) handler lookup.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

from soothe.core.event_catalog import (
    CONTEXT_INGESTED,
    CONTEXT_PROJECTED,
    ERROR,
    GOAL_COMPLETED,
    GOAL_CREATED,
    GOAL_FAILED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    MEMORY_RECALLED,
    MEMORY_STORED,
    PLAN_BATCH_STARTED,
    PLAN_CREATED,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    POLICY_CHECKED,
    POLICY_DENIED,
    REGISTRY,
    THREAD_CREATED,
    THREAD_ENDED,
    THREAD_RESUMED,
    THREAD_SAVED,
    THREAD_STARTED,
)
from soothe.subagents.browser.events import (
    SUBAGENT_BROWSER_CDP,
    SUBAGENT_BROWSER_STEP,
)
from soothe.tools.display_names import get_tool_display_name
from soothe.tools.research.events import (
    TOOL_RESEARCH_ANALYZE,
    TOOL_RESEARCH_COMPLETED,
    TOOL_RESEARCH_GATHER,
    TOOL_RESEARCH_GATHER_DONE,
    TOOL_RESEARCH_QUERIES_GENERATED,
    TOOL_RESEARCH_SYNTHESIZE,
)
from soothe.tools.web_search.events import (
    TOOL_WEBSEARCH_CRAWL_COMPLETED,
    TOOL_WEBSEARCH_CRAWL_FAILED,
    TOOL_WEBSEARCH_CRAWL_STARTED,
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
    TOOL_WEBSEARCH_SEARCH_STARTED,
)
from soothe.ux.shared.progress_verbosity import ProgressVerbosity, should_show

logger = logging.getLogger(__name__)

_MAX_INLINE_QUERIES = 3
_EVENT_TYPE_MIN_SEGMENTS = 4


class CliEventRenderer:
    """Headless CLI event renderer using registry dispatch (RFC-0015)."""

    def __init__(self) -> None:
        """Initialize the CLI event renderer with registered handlers."""
        self._registry = REGISTRY
        self._handlers: dict[str, Callable[[dict], list[str]]] = {}
        self._register_handlers()

    def render(
        self,
        event: dict[str, Any],
        *,
        verbosity: ProgressVerbosity = "normal",
        prefix: str | None = None,  # noqa: ARG002 - kept for backward compatibility
    ) -> None:
        """Render event to stderr using registry dispatch.

        Args:
            event: Event dict with 'type' key.
            verbosity: Verbosity level for filtering.
            prefix: Optional prefix (unused in new implementation, kept for compat).
        """
        etype = event.get("type", "")
        meta = self._registry.get_meta(etype)

        # Check verbosity
        if meta and not should_show(meta.verbosity, verbosity):
            return

        if etype == POLICY_CHECKED:
            parts = self._render_policy_checked(event, verbosity)
            if not parts:
                return
            tag = "policy"
            line = f"[{tag}] {' '.join(parts)}\n"
            sys.stderr.write(line)
            sys.stderr.flush()
            return

        # Dispatch to handler
        handler = self._handlers.get(etype, self._default_handler)
        parts = handler(event)

        if not parts:
            return

        # Format and write
        tag = self._get_tag(etype, meta)
        line = f"[{tag}] {' '.join(parts)}\n"
        sys.stderr.write(line)
        sys.stderr.flush()

    def _register_handlers(self) -> None:
        """Register event-specific handlers for O(1) dispatch."""
        # Websearch tool events
        self._handlers[TOOL_WEBSEARCH_SEARCH_STARTED] = self._render_search_started
        self._handlers[TOOL_WEBSEARCH_SEARCH_COMPLETED] = self._render_search_completed
        self._handlers[TOOL_WEBSEARCH_SEARCH_FAILED] = self._render_search_failed
        self._handlers[TOOL_WEBSEARCH_CRAWL_STARTED] = self._render_crawl_started
        self._handlers[TOOL_WEBSEARCH_CRAWL_COMPLETED] = self._render_crawl_completed
        self._handlers[TOOL_WEBSEARCH_CRAWL_FAILED] = self._render_crawl_failed

        # Research tool events
        self._handlers[TOOL_RESEARCH_ANALYZE] = self._render_research_analyze
        self._handlers[TOOL_RESEARCH_QUERIES_GENERATED] = self._render_research_queries
        self._handlers[TOOL_RESEARCH_GATHER] = self._render_research_gather
        self._handlers[TOOL_RESEARCH_GATHER_DONE] = self._render_research_gather_done
        self._handlers[TOOL_RESEARCH_SYNTHESIZE] = self._render_research_synthesize
        self._handlers[TOOL_RESEARCH_COMPLETED] = self._render_research_completed

        # Subagent browser events
        self._handlers[SUBAGENT_BROWSER_STEP] = self._render_browser_step
        self._handlers[SUBAGENT_BROWSER_CDP] = self._render_browser_cdp

        # Protocol events
        self._handlers[CONTEXT_PROJECTED] = self._render_context_projected
        self._handlers[CONTEXT_INGESTED] = self._render_context_ingested
        self._handlers[MEMORY_RECALLED] = self._render_memory_recalled
        self._handlers[MEMORY_STORED] = self._render_memory_stored
        self._handlers[PLAN_CREATED] = self._render_plan_created
        self._handlers[PLAN_STEP_STARTED] = self._render_plan_step_started
        self._handlers[PLAN_STEP_COMPLETED] = self._render_plan_step_completed
        self._handlers[PLAN_STEP_FAILED] = self._render_plan_step_failed
        self._handlers[PLAN_BATCH_STARTED] = self._render_plan_batch_started
        self._handlers[PLAN_REFLECTED] = self._render_plan_reflected
        self._handlers[POLICY_CHECKED] = self._render_policy_checked
        self._handlers[POLICY_DENIED] = self._render_policy_denied
        self._handlers[GOAL_CREATED] = self._render_goal_created
        self._handlers[GOAL_COMPLETED] = self._render_goal_completed
        self._handlers[GOAL_FAILED] = self._render_goal_failed

        # Lifecycle events
        self._handlers[THREAD_CREATED] = self._render_thread_created
        self._handlers[THREAD_STARTED] = self._render_thread_started
        self._handlers[THREAD_RESUMED] = self._render_thread_resumed
        self._handlers[THREAD_SAVED] = self._render_thread_saved
        self._handlers[THREAD_ENDED] = self._render_thread_ended
        self._handlers[ITERATION_STARTED] = self._render_iteration_started
        self._handlers[ITERATION_COMPLETED] = self._render_iteration_completed

        # Error events
        self._handlers[ERROR] = self._render_error

    def _get_tag(self, etype: str, meta: Any) -> str:
        """Get tag for event type."""
        if meta:
            return meta.component
        # Fallback for unknown events
        parts = etype.split(".")
        if len(parts) >= _EVENT_TYPE_MIN_SEGMENTS and parts[0] == "soothe":
            domain = parts[1]
            if domain == "tool":
                return "tool"
            if domain == "subagent":
                return "subagent"
            if domain == "error":
                return "error"
            if domain in ("protocol", "lifecycle", "output"):
                return parts[2]
        return "custom"

    def _default_handler(self, event: dict[str, Any]) -> list[str]:
        """Default handler for unregistered events using summary template."""
        etype = event.get("type", "")
        meta = self._registry.get_meta(etype)

        if meta and meta.summary_template:
            try:
                summary = meta.summary_template.format(**event)
            except KeyError:
                # Fallback: extract key fields
                summary = event.get("description", event.get("summary", str(event)))
            else:
                return [summary]

        # Fallback: extract key fields
        summary = event.get("description", event.get("summary", str(event)))
        return [str(summary)[:120]]

    # --- Tool event handlers ---

    def _render_search_started(self, event: dict[str, Any]) -> list[str]:
        query = event.get("query", "")
        engines = event.get("engines", [])
        display_name = get_tool_display_name("search_web")
        parts = [f"{display_name}:", str(query)[:40]]
        if engines:
            parts.append(f"({', '.join(engines[:_MAX_INLINE_QUERIES])})")
        return parts

    def _render_search_completed(self, event: dict[str, Any]) -> list[str]:
        count = event.get("result_count", 0)
        response_time = event.get("response_time")
        parts = [f"Found {count} results"]
        if response_time:
            parts.append(f"({response_time:.1f}s)")
        return parts

    def _render_search_failed(self, event: dict[str, Any]) -> list[str]:
        error = event.get("error", "unknown error")
        return [f"Search failed: {str(error)[:40]}"]

    def _render_crawl_started(self, event: dict[str, Any]) -> list[str]:
        url = event.get("url", "")
        return [f"Crawling: {str(url)[:50]}"]

    def _render_crawl_completed(self, event: dict[str, Any]) -> list[str]:
        content_length = event.get("content_length", 0)
        return [f"Crawl complete: {content_length} bytes"]

    def _render_crawl_failed(self, event: dict[str, Any]) -> list[str]:
        error = event.get("error", "unknown error")
        return [f"Crawl failed: {str(error)[:40]}"]

    # --- Research tool event handlers ---

    def _render_research_analyze(self, event: dict[str, Any]) -> list[str]:
        topic = str(event.get("topic", ""))[:50]
        return [f"Analyzing: {topic}"]

    def _render_research_queries(self, event: dict[str, Any]) -> list[str]:
        queries = event.get("queries", [])
        count = len(queries)
        parts = [f"Generated {count} queries"]
        if queries and count <= _MAX_INLINE_QUERIES:
            parts.append(f": {', '.join(str(q)[:30] for q in queries[:_MAX_INLINE_QUERIES])}")
        return parts

    def _render_research_gather(self, event: dict[str, Any]) -> list[str]:
        domain = event.get("domain", "")
        query = str(event.get("query", ""))[:40]
        return [f"Gathering from {domain}: {query}"]

    def _render_research_gather_done(self, event: dict[str, Any]) -> list[str]:
        count = event.get("result_count", 0)
        return [f"Gathered {count} results"]

    def _render_research_synthesize(self, event: dict[str, Any]) -> list[str]:
        total = event.get("total_sources", 0)
        return [f"Synthesizing {total} sources"]

    def _render_research_completed(self, event: dict[str, Any]) -> list[str]:
        length = event.get("answer_length", 0)
        return [f"Research completed ({length} chars)"]

    # --- Subagent event handlers ---

    def _render_browser_step(self, event: dict[str, Any]) -> list[str]:
        step = event.get("step", "?")
        action = str(event.get("action", ""))[:40]
        url = str(event.get("url", ""))[:35]
        parts = [f"Step {step}"]
        if action:
            parts.append(f": {action}")
        if url:
            parts.append(f"@ {url}")
        return parts

    def _render_browser_cdp(self, event: dict[str, Any]) -> list[str]:
        status = event.get("status", "")
        cdp_url = event.get("cdp_url", "")
        if status == "connected":
            return [f"Connected to existing browser: {cdp_url}"]
        if status == "not_found":
            return ["No existing browser found, launching new instance"]
        return [f"CDP status: {status}"]

    # --- Protocol event handlers ---

    def _render_context_projected(self, event: dict[str, Any]) -> list[str]:
        entries = event.get("entries", 0)
        tokens = event.get("tokens", 0)
        return [f"Projected {entries} entries ({tokens:,} tokens)"]

    def _render_context_ingested(self, event: dict[str, Any]) -> list[str]:
        source = event.get("source", "?")
        preview = str(event.get("content_preview", ""))[:60]
        return [f"Ingested from {source}: {preview}"]

    def _render_memory_recalled(self, event: dict[str, Any]) -> list[str]:
        count = event.get("count", 0)
        query = str(event.get("query", ""))[:40]
        return [f"Recalled {count} memories for: {query}"]

    def _render_memory_stored(self, event: dict[str, Any]) -> list[str]:
        source_thread = event.get("source_thread", "?")
        return [f"Stored memory from thread {source_thread}"]

    def _render_plan_created(self, event: dict[str, Any]) -> list[str]:
        goal = event.get("goal", "")
        steps = event.get("steps", [])
        return [f"Plan: {goal[:80]} ({len(steps)} steps)"]

    def _render_plan_step_started(self, event: dict[str, Any]) -> list[str]:
        description = event.get("description", "")
        step_id = event.get("step_id", "?")
        return [f"Step {step_id}: {description[:80]}"]

    def _render_plan_step_completed(self, event: dict[str, Any]) -> list[str]:
        step_id = event.get("step_id", "?")
        success = event.get("success", False)
        duration_ms = event.get("duration_ms", 0)
        status = "✓" if success else "✗"
        return [f"Step {step_id} {status} ({duration_ms}ms)"]

    def _render_plan_step_failed(self, event: dict[str, Any]) -> list[str]:
        step_id = event.get("step_id", "?")
        error = event.get("error", "unknown error")
        return [f"Step {step_id} failed: {str(error)[:60]}"]

    def _render_plan_batch_started(self, event: dict[str, Any]) -> list[str]:
        batch_index = event.get("batch_index", 0)
        step_ids = event.get("step_ids", [])
        parallel_count = event.get("parallel_count", 1)
        return [f"Batch {batch_index}: {len(step_ids)} steps (parallelism={parallel_count})"]

    def _render_plan_reflected(self, event: dict[str, Any]) -> list[str]:
        should_revise = event.get("should_revise", False)
        assessment = str(event.get("assessment", ""))[:80]
        action = "Revising plan" if should_revise else "Plan accepted"
        return [f"{action}: {assessment}"]

    def _render_policy_checked(self, event: dict[str, Any], verbosity: ProgressVerbosity) -> list[str]:
        """Render policy.checked event with conditional suppression.

        In debug mode, show all policy events.
        In normal mode, suppress "allow" messages but show "deny" messages.
        Log all policy events to file for audit trail.
        """
        verdict = event.get("verdict", "?")
        profile = event.get("profile")

        # Always log to file for audit trail
        detail = f"Policy: {verdict}"
        if profile:
            detail += f" (profile={profile})"
        logger.info("Policy event: %s", detail)

        # In normal mode, suppress "allow" events from display
        if verdict == "allow" and verbosity != "debug":
            return []

        parts = [verdict]
        if profile:
            parts.append(f"(profile={profile})")
        return parts

    def _render_policy_denied(self, event: dict[str, Any]) -> list[str]:
        reason = event.get("reason", "denied")
        profile = event.get("profile")
        parts = [reason]
        if profile:
            parts.append(f"(profile={profile})")
        return parts

    def _render_goal_created(self, event: dict[str, Any]) -> list[str]:
        goal_id = event.get("goal_id", "?")
        description = event.get("description", "")
        return [f"Goal {goal_id}: {description[:80]}"]

    def _render_goal_completed(self, event: dict[str, Any]) -> list[str]:
        goal_id = event.get("goal_id", "?")
        return [f"Goal {goal_id} completed ✓"]

    def _render_goal_failed(self, event: dict[str, Any]) -> list[str]:
        goal_id = event.get("goal_id", "?")
        error = event.get("error", "unknown error")
        return [f"Goal {goal_id} failed: {str(error)[:60]}"]

    # --- Lifecycle event handlers ---

    def _render_thread_created(self, event: dict[str, Any]) -> list[str]:
        thread_id = event.get("thread_id", "?")
        return [f"Thread created: {thread_id}"]

    def _render_thread_started(self, event: dict[str, Any]) -> list[str]:
        thread_id = event.get("thread_id", "?")
        protocols = event.get("protocols", {})
        proto_list = list(protocols.keys()) if protocols else []
        proto_str = f" [{', '.join(proto_list[:3])}]" if proto_list else ""
        return [f"Thread started: {thread_id}{proto_str}"]

    def _render_thread_resumed(self, event: dict[str, Any]) -> list[str]:
        thread_id = event.get("thread_id", "?")
        return [f"Thread resumed: {thread_id}"]

    def _render_thread_saved(self, event: dict[str, Any]) -> list[str]:
        thread_id = event.get("thread_id", "?")
        return [f"Thread saved: {thread_id}"]

    def _render_thread_ended(self, event: dict[str, Any]) -> list[str]:
        thread_id = event.get("thread_id", "?")
        return [f"Thread ended: {thread_id}"]

    def _render_iteration_started(self, event: dict[str, Any]) -> list[str]:
        iteration = event.get("iteration", "?")
        goal_id = event.get("goal_id", "?")
        parallel_goals = event.get("parallel_goals", 1)
        return [f"Iteration {iteration} started (goal={goal_id}, parallel={parallel_goals})"]

    def _render_iteration_completed(self, event: dict[str, Any]) -> list[str]:
        iteration = event.get("iteration", "?")
        outcome = event.get("outcome", "?")
        duration_ms = event.get("duration_ms", 0)
        return [f"Iteration {iteration} completed: {outcome} ({duration_ms}ms)"]

    # --- Error event handlers ---

    def _render_error(self, event: dict[str, Any]) -> list[str]:
        error = event.get("error", "unknown error")
        return [f"ERROR: {str(error)[:100]}"]


# Singleton instance for CLI rendering
_CLI_RENDERER = CliEventRenderer()


def render_progress_event(
    data: dict,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render a soothe.* event as a structured progress line to stderr.

    This is the backward-compatible entry point that uses the new
    registry-based dispatch internally.

    Args:
        data: Event dict with 'type' key.
        prefix: Optional prefix (unused in new implementation, kept for compat).
        verbosity: Verbosity level for filtering.
    """
    _CLI_RENDERER.render(data, verbosity=verbosity, prefix=prefix)
