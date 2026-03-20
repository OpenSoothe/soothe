"""Registry-based TUI event renderer for Rich Text activity panel.

This module implements RFC-0015's registry-based dispatch to replace the old
O(n) if-elif chains with O(1) handler lookup for TUI rendering.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rich.text import Text

from soothe.cli.message_processing import strip_internal_tags
from soothe.cli.progress_verbosity import ProgressVerbosity, should_show
from soothe.core.event_catalog import REGISTRY
from soothe.core.events import (
    CHITCHAT_RESPONSE,
    CONTEXT_INGESTED,
    CONTEXT_PROJECTED,
    FINAL_REPORT,
    GOAL_BATCH_STARTED,
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
    SUBAGENT_BROWSER_CDP,
    SUBAGENT_BROWSER_STEP,
    THREAD_CREATED,
    THREAD_RESUMED,
    THREAD_SAVED,
    TOOL_RESEARCH_ANALYZE,
    TOOL_RESEARCH_COMPLETED,
    TOOL_RESEARCH_GATHER,
    TOOL_RESEARCH_GATHER_DONE,
    TOOL_RESEARCH_QUERIES_GENERATED,
    TOOL_RESEARCH_SYNTHESIZE,
    TOOL_WEBSEARCH_CRAWL_COMPLETED,
    TOOL_WEBSEARCH_CRAWL_FAILED,
    TOOL_WEBSEARCH_CRAWL_STARTED,
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
    TOOL_WEBSEARCH_SEARCH_STARTED,
)

if TYPE_CHECKING:
    from soothe.cli.tui.state import TuiState

logger = logging.getLogger(__name__)

_MAX_INLINE_QUERIES = 3
_ACTIVITY_MAX = 300


def _truncate(text: str, limit: int = 80) -> str:
    """Truncate text with ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


class TuiEventRenderer:
    """TUI activity panel renderer using registry dispatch (RFC-0015)."""

    def __init__(self) -> None:
        """Initialize the TUI event renderer with registered handlers."""
        self._registry = REGISTRY
        self._handlers: dict[str, Callable[[dict, TuiState, ProgressVerbosity], None]] = {}
        self._register_handlers()

    def render_protocol_event(
        self,
        event: dict[str, Any],
        state: TuiState,
        *,
        verbosity: ProgressVerbosity = "normal",
    ) -> None:
        """Render a protocol event to TUI activity panel.

        Args:
            event: Event dict with 'type' key.
            state: TUI state for tracking plan steps, etc.
            verbosity: Verbosity level for filtering.
        """
        etype = event.get("type", "")
        meta = self._registry.get_meta(etype)

        # Check verbosity
        if meta and not should_show(meta.verbosity, verbosity):
            return

        if etype in (
            TOOL_WEBSEARCH_SEARCH_STARTED,
            TOOL_WEBSEARCH_SEARCH_COMPLETED,
            TOOL_WEBSEARCH_SEARCH_FAILED,
            TOOL_WEBSEARCH_CRAWL_STARTED,
            TOOL_WEBSEARCH_CRAWL_COMPLETED,
            TOOL_WEBSEARCH_CRAWL_FAILED,
        ):
            self._render_tool_event(event, state, verbosity=verbosity)
            return

        # Dispatch to handler
        handler = self._handlers.get(etype)
        if handler:
            handler(event, state, verbosity)

    def _register_handlers(self) -> None:
        """Register event-specific handlers for O(1) dispatch."""
        # Protocol events
        self._handlers[CONTEXT_PROJECTED] = self._render_context_projected
        self._handlers[CONTEXT_INGESTED] = self._render_context_ingested
        self._handlers[MEMORY_RECALLED] = self._render_memory_recalled
        self._handlers[MEMORY_STORED] = self._render_memory_stored
        self._handlers[PLAN_CREATED] = self._render_plan_created
        self._handlers[PLAN_STEP_STARTED] = self._render_plan_step_started
        self._handlers[PLAN_STEP_COMPLETED] = self._render_plan_step_completed
        self._handlers[PLAN_STEP_FAILED] = self._render_plan_step_failed
        self._handlers[PLAN_REFLECTED] = self._render_plan_reflected
        self._handlers[PLAN_BATCH_STARTED] = self._render_plan_batch_started
        self._handlers[GOAL_BATCH_STARTED] = self._render_goal_batch_started
        self._handlers[POLICY_CHECKED] = self._render_policy_checked
        self._handlers[POLICY_DENIED] = self._render_policy_denied

        # Lifecycle events
        self._handlers[THREAD_CREATED] = self._render_thread_created
        self._handlers[THREAD_RESUMED] = self._render_thread_resumed
        self._handlers[THREAD_SAVED] = self._render_thread_saved
        self._handlers[ITERATION_STARTED] = self._render_iteration_started
        self._handlers[ITERATION_COMPLETED] = self._render_iteration_completed

        # Subagent progress events
        self._handlers[SUBAGENT_BROWSER_STEP] = self._render_browser_step
        self._handlers[SUBAGENT_BROWSER_CDP] = self._render_browser_cdp

        # Research tool events
        self._handlers[TOOL_RESEARCH_ANALYZE] = self._render_research_analyze
        self._handlers[TOOL_RESEARCH_QUERIES_GENERATED] = self._render_research_queries
        self._handlers[TOOL_RESEARCH_GATHER] = self._render_research_gather
        self._handlers[TOOL_RESEARCH_GATHER_DONE] = self._render_research_gather_done
        self._handlers[TOOL_RESEARCH_SYNTHESIZE] = self._render_research_synthesize
        self._handlers[TOOL_RESEARCH_COMPLETED] = self._render_research_completed

        # Output events
        self._handlers[CHITCHAT_RESPONSE] = self._render_chitchat_response
        self._handlers[FINAL_REPORT] = self._render_final_report

    def _add_activity(self, state: TuiState, line: Text) -> None:
        """Add activity line to state."""
        state.activity_lines.append(line)
        logger.info("Activity: %s", line.plain)
        if len(state.activity_lines) > _ACTIVITY_MAX:
            state.activity_lines = state.activity_lines[-_ACTIVITY_MAX:]

    def _add_activity_from_event(self, state: TuiState, line: Text, event_data: dict[str, Any]) -> None:
        """Add activity line and associate with step if event has step_id.

        Args:
            state: TUI state
            line: Activity line (Rich Text)
            event_data: Event dict that may contain 'step_id' field
        """
        # Store in activity_lines for logging purposes
        state.activity_lines.append(line)
        logger.info("Activity: %s", line.plain)
        if len(state.activity_lines) > _ACTIVITY_MAX:
            state.activity_lines = state.activity_lines[-_ACTIVITY_MAX:]

        # Extract step_id from event if present
        step_id = event_data.get("step_id")

        # If this activity belongs to a step, update that step's current_activity
        if step_id and state.current_plan:
            for step in state.current_plan.steps:
                if step.id == step_id:
                    # Store plain text for tree rendering
                    step.current_activity = line.plain
                    return

        # No step_id - this is a general activity
        if state.current_plan:
            state.current_plan.general_activity = line.plain

    def _set_plan_step_status_by_id(self, state: TuiState, step_id: str, status: str) -> None:
        """Update a plan step status by step ID (RFC-0009)."""
        if not state.current_plan:
            return
        for step in state.current_plan.steps:
            if step.id == step_id:
                step.status = status
                return

    def _set_plan_step_status(self, state: TuiState, index: int, status: str) -> None:
        """Update a plan step status by index if the current plan exists."""
        if not state.current_plan:
            return
        if 0 <= index < len(state.current_plan.steps):
            state.current_plan.steps[index].status = status

    # --- Tool event handlers ---

    def _render_tool_event(
        self,
        event: dict[str, Any],
        state: TuiState,
        *,
        verbosity: ProgressVerbosity = "normal",
    ) -> None:
        """Render tool activity progress events."""
        if not should_show("tool_activity", verbosity):
            return

        etype = event.get("type", "")

        if etype == TOOL_WEBSEARCH_SEARCH_STARTED:
            query = event.get("query", "")
            engines = event.get("engines", [])
            summary = f"Searching: {_truncate(str(query), 40)}"
            if engines:
                summary += f" ({', '.join(engines[:3])})"
            self._add_activity_from_event(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")), event)

        elif etype == TOOL_WEBSEARCH_SEARCH_COMPLETED:
            count = event.get("result_count", 0)
            response_time = event.get("response_time")
            summary = f"Search complete: {count} results"
            if response_time:
                summary += f" ({response_time:.1f}s)"
            self._add_activity_from_event(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")), event)

        elif etype == TOOL_WEBSEARCH_SEARCH_FAILED:
            error = event.get("error", "unknown error")
            summary = f"Search failed: {_truncate(str(error), 40)}"
            self._add_activity_from_event(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")), event)

        elif etype == TOOL_WEBSEARCH_CRAWL_STARTED:
            url = event.get("url", "")
            summary = f"Crawling: {_truncate(str(url), 50)}"
            self._add_activity_from_event(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")), event)

        elif etype == TOOL_WEBSEARCH_CRAWL_COMPLETED:
            content_length = event.get("content_length", 0)
            summary = f"Crawl complete: {content_length} bytes"
            self._add_activity_from_event(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")), event)

        elif etype == TOOL_WEBSEARCH_CRAWL_FAILED:
            error = event.get("error", "unknown error")
            summary = f"Crawl failed: {_truncate(str(error), 40)}"
            self._add_activity_from_event(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")), event)

    # --- Protocol event handlers ---

    def _render_context_projected(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        entries = event.get("entries", 0)
        tokens = event.get("tokens", 0)
        self._add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"Context: {entries} entries, {tokens} tokens", "cyan")),
            event,
        )

    def _render_context_ingested(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        source = event.get("source", "")
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Ingested from {source}", "dim cyan")), event
        )

    def _render_memory_recalled(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        count = event.get("count", 0)
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Memory: {count} items recalled", "cyan")), event
        )

    def _render_memory_stored(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        memory_id = event.get("id", "?")
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Stored memory: {memory_id}", "cyan")), event
        )

    def _render_plan_created(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        from soothe.protocols.planner import Plan, PlanStep

        steps_data = event.get("steps", [])
        try:
            steps = [
                PlanStep(
                    id=s.get("id", str(i)),
                    description=s.get("description", ""),
                    status=s.get("status", "pending"),
                    depends_on=s.get("depends_on", []),
                )
                for i, s in enumerate(steps_data)
            ]
            state.current_plan = Plan(goal=event.get("goal", ""), steps=steps)
        except Exception:
            logger.debug("Plan reconstruction failed", exc_info=True)
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Plan: {len(steps_data)} steps", "cyan")), event
        )

    def _render_plan_step_started(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        step_id = event.get("step_id", "")
        index = int(event.get("index", -1))
        description = event.get("description", "")
        if step_id:
            self._set_plan_step_status_by_id(state, step_id, "in_progress")
            self._add_activity_from_event(
                state, Text.assemble(("  . ", "dim"), (f"Step {step_id}: {description}", "yellow")), event
            )
        elif index >= 0:
            self._set_plan_step_status(state, index, "in_progress")
            self._add_activity_from_event(
                state, Text.assemble(("  . ", "dim"), (f"Step {index + 1}: {description}", "yellow")), event
            )

    def _render_plan_step_completed(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        step_id = event.get("step_id", "")
        index = int(event.get("index", -1))
        success = bool(event.get("success", False))
        duration = event.get("duration_ms", 0)
        status = "completed" if success else "failed"

        if step_id:
            self._set_plan_step_status_by_id(state, step_id, status)
            # Clear current_activity for completed step
            if state.current_plan:
                for step in state.current_plan.steps:
                    if step.id == step_id:
                        step.current_activity = None
                        break
            dur_str = f" ({duration}ms)" if duration else ""
            label = f"Step {step_id}: {'done' if success else 'failed'}{dur_str}"
        elif index >= 0:
            self._set_plan_step_status(state, index, status)
            # Clear current_activity for completed step
            if state.current_plan and 0 <= index < len(state.current_plan.steps):
                state.current_plan.steps[index].current_activity = None
            label = f"Step {index + 1}: {'done' if success else 'failed'}"
        else:
            label = f"Step: {'done' if success else 'failed'}"

        self._add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (label, "green" if success else "red")),
            event,
        )

    def _render_plan_step_failed(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        step_id = event.get("step_id", "")
        error = event.get("error", "")[:80]
        if step_id:
            self._set_plan_step_status_by_id(state, step_id, "failed")
            # Clear current_activity for failed step
            if state.current_plan:
                for step in state.current_plan.steps:
                    if step.id == step_id:
                        step.current_activity = None
                        break
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Step {step_id}: FAILED - {error}", "bold red")), event
        )

    def _render_plan_reflected(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        assessment = event.get("assessment", "")[:60]
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Reflected: {assessment}", "dim italic")), event
        )

    def _render_plan_batch_started(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        parallel = event.get("parallel_count", 1)
        if parallel > 1:
            self._add_activity_from_event(
                state, Text.assemble(("  . ", "dim"), (f"Batch: {parallel} steps in parallel", "cyan bold")), event
            )

    def _render_goal_batch_started(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        parallel = event.get("parallel_count", 1)
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Goals: {parallel} running in parallel", "cyan bold")), event
        )

    def _render_policy_checked(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:
        """Render policy.checked event with conditional display.

        In debug mode, show all policy events.
        In normal mode, only show deny events.
        """
        verdict = event.get("verdict", "?")
        profile = event.get("profile")
        detail = f"Policy: {verdict}"
        if profile:
            detail += f" (profile={profile})"

        # Show deny events always, and show allow events in debug mode
        if verdict == "deny" or verbosity == "debug":
            self._add_activity_from_event(
                state,
                Text.assemble(("  . ", "dim"), (detail, "bold red" if verdict == "deny" else "dim")),
                event,
            )
        else:
            # Log allow events to file only in normal mode
            logger.info("Activity:   . %s", detail)

    def _render_policy_denied(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        reason = event.get("reason", "")
        profile = event.get("profile")
        detail = f"Denied: {reason}"
        if profile:
            detail += f" (profile={profile})"
        self._add_activity_from_event(state, Text.assemble(("  ! ", "bold red"), (detail, "red")), event)

    # --- Lifecycle event handlers ---

    def _render_thread_created(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        tid = event.get("thread_id", "?")
        state.thread_id = tid
        self._add_activity_from_event(state, Text.assemble(("  . ", "dim"), (f"Thread: {tid}", "dim")), event)

    def _render_thread_resumed(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        tid = event.get("thread_id", "?")
        state.thread_id = tid
        self._add_activity_from_event(state, Text.assemble(("  . ", "dim"), (f"Resumed thread: {tid}", "dim")), event)

    def _render_thread_saved(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        tid = event.get("thread_id", state.thread_id or "?")
        self._add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Saved thread: {tid}", "dim cyan")), event
        )

    def _render_iteration_started(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        iteration = event.get("iteration", "?")
        goal_id = event.get("goal_id", "?")
        goal_desc = event.get("goal_description", "")[:60]
        self._add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"Iteration {iteration}: {goal_desc} (goal={goal_id})", "yellow")),
            event,
        )

    def _render_iteration_completed(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        iteration = event.get("iteration", "?")
        outcome = event.get("outcome", "?")
        duration = event.get("duration_ms", 0)
        self._add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"Iteration {iteration}: {outcome} ({duration}ms)", "green")),
            event,
        )

    # --- Subagent event handlers ---

    def _render_browser_step(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        step = event.get("step", "?")
        action = _truncate(str(event.get("action", "")), 50)
        url = _truncate(str(event.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[browser] ", "cyan"), (summary, "yellow")), event
        )

    def _render_browser_cdp(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        status = event.get("status", "")
        if status == "connected":
            summary = "Connected to existing browser"
        elif status == "not_found":
            summary = "No existing browser found, launching new"
        else:
            summary = f"Browser CDP: {status}"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[browser] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_analyze(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        topic = _truncate(str(event.get("topic", "")), 50)
        summary = f"Analyzing: {topic}"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_queries(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        count = event.get("count", 0)
        queries = event.get("queries", [])
        summary = f"Generated {count} queries"
        if queries and len(queries) <= _MAX_INLINE_QUERIES:
            summary += f": {', '.join(_truncate(str(q), 30) for q in queries[:_MAX_INLINE_QUERIES])}"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_gather(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        query = event.get("query", "")
        domain = event.get("domain", "unknown")
        summary = f"Gathering from {domain}: {_truncate(str(query), 40)}"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_gather_done(
        self,
        event: dict[str, Any],
        state: TuiState,
        verbosity: ProgressVerbosity,  # noqa: ARG002
    ) -> None:
        count = event.get("result_count", 0)
        sources = event.get("sources_used", [])
        summary = f"Gathered {count} results from {len(sources)} sources"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_synthesize(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        total = event.get("total_sources", 0)
        summary = f"Synthesizing {total} sources"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "yellow")), event
        )

    def _render_research_completed(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        length = event.get("answer_length", 0)
        summary = f"Completed ({length} chars)"
        self._add_activity_from_event(
            state, Text.assemble(("  ", ""), ("[research] ", "cyan"), (summary, "green")), event
        )

    # --- Output event handlers ---

    def _render_chitchat_response(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        content = event.get("content", "")
        if content:
            cleaned = strip_internal_tags(content)
            if cleaned:
                state.full_response.append(cleaned)

    def _render_final_report(self, event: dict[str, Any], state: TuiState, verbosity: ProgressVerbosity) -> None:  # noqa: ARG002
        summary = event.get("summary", "")
        if summary:
            state.full_response.append(f"\n{summary}")
        # Reset multi-step flag after final report
        state.multi_step_active = False


# Singleton instance for TUI rendering
_TUI_RENDERER = TuiEventRenderer()


def handle_protocol_event(
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render a soothe.* protocol custom event as an activity line.

    This is the backward-compatible entry point that uses the new
    registry-based dispatch internally.

    Args:
        data: Event dict with 'type' key.
        state: TUI state for tracking plan steps, etc.
        verbosity: Verbosity level for filtering.
    """
    _TUI_RENDERER.render_protocol_event(data, state, verbosity=verbosity)
