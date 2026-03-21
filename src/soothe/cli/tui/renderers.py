"""TUI event rendering functions."""

from __future__ import annotations

import logging
from typing import Any

from rich.text import Text

from soothe.cli.message_processing import (
    extract_tool_brief as _extract_tool_brief,
    format_tool_call_args,
)
from soothe.cli.progress_verbosity import ProgressVerbosity, should_show
from soothe.cli.tui.state import TuiState
from soothe.core.events import (
    SUBAGENT_BROWSER_CDP,
    SUBAGENT_BROWSER_STEP,
    SUBAGENT_CLAUDE_RESULT,
    SUBAGENT_CLAUDE_TEXT,
    SUBAGENT_CLAUDE_TOOL_USE,
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
from soothe.tools.display_names import get_tool_display_name

logger = logging.getLogger(__name__)

_ACTIVITY_MAX = 300
_MAX_INLINE_QUERIES = 3
_STATUS_MARKERS: dict[str, tuple[str, str]] = {
    "pending": ("[ ]", "dim"),
    "in_progress": ("[>]", "bold yellow"),
    "completed": ("[+]", "bold green"),
    "failed": ("[x]", "bold red"),
}


def _truncate(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _add_activity(state: TuiState, line: Text) -> None:
    state.activity_lines.append(line)
    logger.info("Activity: %s", line.plain)
    if len(state.activity_lines) > _ACTIVITY_MAX:
        state.activity_lines = state.activity_lines[-_ACTIVITY_MAX:]


def _add_activity_from_event(state: TuiState, line: Text, event_data: dict[str, Any]) -> None:
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


def _set_plan_step_status(state: TuiState, index: int, status: str) -> None:
    """Update a plan step status by index if the current plan exists."""
    if not state.current_plan:
        return
    if 0 <= index < len(state.current_plan.steps):
        state.current_plan.steps[index].status = status


def _set_plan_step_status_by_id(state: TuiState, step_id: str, status: str) -> None:
    """Update a plan step status by step ID (RFC-0009)."""
    if not state.current_plan:
        return
    for step in state.current_plan.steps:
        if step.id == step_id:
            step.status = status
            return


def _handle_protocol_event(
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render a soothe.* protocol custom event as an activity line.

    This function delegates to TuiEventRenderer which uses registry-based
    O(1) dispatch instead of O(n) if-elif chains (RFC-0015).

    Args:
        data: Event dict with 'type' key.
        state: TUI state for tracking plan steps, etc.
        verbosity: Verbosity level for filtering.
    """
    from soothe.cli.tui.tui_event_renderer import handle_protocol_event as _handle

    _handle(data, state, verbosity=verbosity)


def _handle_tool_activity_event(
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render tool activity progress events."""
    if not should_show("tool_activity", verbosity):
        return

    etype = data.get("type", "")

    if etype == TOOL_WEBSEARCH_SEARCH_STARTED:
        query = data.get("query", "")
        engines = data.get("engines", [])
        summary = f"Searching: {_truncate(str(query), 40)}"
        if engines:
            summary += f" ({', '.join(engines[:3])})"
        _add_activity_from_event(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")), data)

    elif etype == TOOL_WEBSEARCH_SEARCH_COMPLETED:
        count = data.get("result_count", 0)
        response_time = data.get("response_time")
        summary = f"Search complete: {count} results"
        if response_time:
            summary += f" ({response_time:.1f}s)"
        _add_activity_from_event(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")), data)

    elif etype == TOOL_WEBSEARCH_SEARCH_FAILED:
        error = data.get("error", "unknown error")
        summary = f"Search failed: {_truncate(str(error), 40)}"
        _add_activity_from_event(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")), data)

    elif etype == TOOL_WEBSEARCH_CRAWL_STARTED:
        url = data.get("url", "")
        summary = f"Crawling: {_truncate(str(url), 50)}"
        _add_activity_from_event(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")), data)

    elif etype == TOOL_WEBSEARCH_CRAWL_COMPLETED:
        content_length = data.get("content_length", 0)
        summary = f"Crawl complete: {content_length} bytes"
        _add_activity_from_event(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")), data)

    elif etype == TOOL_WEBSEARCH_CRAWL_FAILED:
        error = data.get("error", "unknown error")
        summary = f"Crawl failed: {_truncate(str(error), 40)}"
        _add_activity_from_event(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")), data)


def _handle_subagent_progress(
    namespace: tuple[str, ...],
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render key subagent progress events visible at normal verbosity."""
    if not should_show("subagent_progress", verbosity):
        return
    from soothe.cli.tui_shared import _resolve_namespace_label

    label = _resolve_namespace_label(namespace, state)
    state.subagent_tracker.update_from_custom(label, data)
    tag = label or "subagent"
    etype = data.get("type", "")

    # Format progress events with user-friendly messages
    if etype == SUBAGENT_BROWSER_STEP:
        step = data.get("step", "?")
        action = _truncate(str(data.get("action", "")), 50)
        url = _truncate(str(data.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
    elif etype == SUBAGENT_BROWSER_CDP:
        status = data.get("status", "")
        if status == "connected":
            summary = "Connected to existing browser"
        elif status == "not_found":
            summary = "No existing browser found, launching new"
        else:
            summary = f"Browser CDP: {status}"
    elif etype == TOOL_RESEARCH_ANALYZE:
        topic = _truncate(str(data.get("topic", "")), 50)
        summary = f"Analyzing: {topic}"
    elif etype == TOOL_RESEARCH_QUERIES_GENERATED:
        count = data.get("count", 0)
        queries = data.get("queries", [])
        summary = f"Generated {count} queries"
        if queries and len(queries) <= _MAX_INLINE_QUERIES:
            summary += f": {', '.join(_truncate(str(q), 30) for q in queries[:_MAX_INLINE_QUERIES])}"
    elif etype == TOOL_RESEARCH_GATHER:
        domain = data.get("domain", "unknown")
        query = _truncate(str(data.get("query", "")), 40)
        summary = f"Gathering from {domain}: {query}"
    elif etype == TOOL_RESEARCH_GATHER_DONE:
        count = data.get("result_count", 0)
        sources = data.get("sources_used", [])
        summary = f"Gathered {count} results from {len(sources)} sources"
    elif etype == TOOL_RESEARCH_SYNTHESIZE:
        summary = "Synthesizing findings"
    elif etype == TOOL_RESEARCH_COMPLETED:
        summary = "Research completed"
    else:
        # Fallback for any other progress events
        summary = etype.replace("soothe.", "").replace("_", " ").title()

    logger.info("Subagent progress [%s]: %s", tag, summary)
    _add_activity_from_event(state, Text.assemble(("  ", ""), (f"[{tag}] ", "cyan"), (summary, "yellow")), data)


def _handle_subagent_custom(
    namespace: tuple[str, ...],
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render subagent custom events into readable activity lines."""
    if not should_show("subagent_custom", verbosity):
        return
    from soothe.cli.tui_shared import _resolve_namespace_label

    label = _resolve_namespace_label(namespace, state)
    state.subagent_tracker.update_from_custom(label, data)
    tag = label or "subagent"
    etype = data.get("type", "")

    if etype == SUBAGENT_BROWSER_STEP:
        step = data.get("step", "?")
        action = _truncate(str(data.get("action", "")), 50)
        url = _truncate(str(data.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
    elif etype.startswith("soothe.tool.research."):
        label = etype.replace("soothe.tool.research.", "").replace("_", " ")
        topic = data.get("topic", data.get("query", ""))
        summary = label
        if topic:
            summary += f": {_truncate(str(topic), 40)}"
    elif etype == SUBAGENT_CLAUDE_TOOL_USE:
        summary = f"Tool: {data.get('tool', data.get('name', etype))}"
    elif etype == SUBAGENT_CLAUDE_TEXT:
        summary = f"Text: {_truncate(str(data.get('text', '')), 50)}"
    elif etype == SUBAGENT_CLAUDE_RESULT:
        cost = data.get("cost_usd", 0)
        duration = data.get("duration_ms", 0)
        summary = f"Done (${cost:.4f}, {duration}ms)" if cost else "Done"
    elif etype.startswith("soothe.subagent.skillify."):
        summary = etype.replace("soothe.subagent.skillify.", "").replace("_", " ")
        detail = data.get("skill", data.get("query", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    elif etype.startswith("soothe.subagent.weaver."):
        summary = etype.replace("soothe.subagent.weaver.", "").replace("_", " ")
        detail = data.get("agent_name", data.get("task", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    else:
        summary = etype.replace("_", " ")[:50]

    logger.info("Subagent event [%s]: %s", tag, summary)
    logger.debug("Subagent event raw [%s]: %s  data=%s", tag, etype, data)
    _add_activity_from_event(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (summary, "dim")), data)


def _handle_subagent_text_activity(
    namespace: tuple[str, ...],
    text: str,
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render subagent AI text into activity as a filtered summary."""
    if not text or not should_show("subagent_custom", verbosity):
        return
    from soothe.cli.tui_shared import _resolve_namespace_label

    tag = _resolve_namespace_label(namespace, state) if namespace else "subagent"
    brief = _truncate(text.replace("\n", " "), 80)
    _add_activity_from_event(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (f"Text: {brief}", "dim")), {})


def _handle_tool_call_activity(
    state: TuiState,
    name: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
    tool_call: dict[str, Any] | None = None,
) -> None:
    """Render tool-call activity line with user-friendly name."""
    if not name or not should_show("protocol", verbosity):
        return

    # Convert snake_case to CamelCase
    display_name = get_tool_display_name(name)

    # Format arguments if available
    args_str = ""
    if tool_call:
        args_str = format_tool_call_args(name, tool_call)

    if prefix:
        _add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"[{prefix}] {display_name}{args_str}", "blue")),
            {},
        )
    else:
        _add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"{display_name}{args_str}", "blue")),
            {},
        )


def _handle_tool_result_activity(
    state: TuiState,
    tool_name: str,
    content: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render tool-result activity line with user-friendly name."""
    if not should_show("protocol", verbosity):
        return

    # Convert snake_case to CamelCase
    display_name = get_tool_display_name(tool_name)

    brief = _extract_tool_brief(tool_name, content)
    if prefix:
        _add_activity_from_event(
            state,
            Text.assemble(("  > ", "dim green"), (f"[{prefix}] {display_name}", "green"), ("  ", ""), (brief, "dim")),
            {},
        )
    else:
        _add_activity_from_event(
            state,
            Text.assemble(("  > ", "dim green"), (display_name, "green"), ("  ", ""), (brief, "dim")),
            {},
        )


def _handle_generic_custom_activity(
    namespace: tuple[str, ...],
    data: dict[str, Any],
    state: TuiState,
    *,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render generic custom events for debug/thinking views."""
    category = "thinking" if "thinking" in str(data.get("type", "")) else "debug"
    if not should_show(category, verbosity):
        return
    from soothe.cli.tui_shared import _resolve_namespace_label

    tag = _resolve_namespace_label(namespace, state) if namespace else "custom"
    etype = str(data.get("type", "custom"))
    summary = str(data.get("message", "")) or str(data.get("topic", "")) or str(data.get("query", "")) or etype
    _add_activity_from_event(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (summary[:80], "dim")), data)
