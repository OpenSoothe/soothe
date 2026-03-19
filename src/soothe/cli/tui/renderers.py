"""TUI event rendering functions."""

from __future__ import annotations

import logging
from typing import Any

from rich.text import Text

from soothe.cli.progress_verbosity import ProgressVerbosity, should_show
from soothe.cli.tui.state import TuiState

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
    """Render a soothe.* protocol custom event as an activity line."""
    if not should_show("protocol", verbosity):
        return
    etype = data.get("type", "")

    # Tool activity events
    if etype.startswith("soothe.tool."):
        _handle_tool_activity_event(data, state, verbosity=verbosity)
        return

    if etype == "soothe.context.projected":
        entries = data.get("entries", 0)
        tokens = data.get("tokens", 0)
        _add_activity(
            state,
            Text.assemble(("  . ", "dim"), (f"Context: {entries} entries, {tokens} tokens", "cyan")),
        )
    elif etype == "soothe.memory.recalled":
        count = data.get("count", 0)
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Memory: {count} items recalled", "cyan")))
    elif etype == "soothe.plan.created":
        from soothe.protocols.planner import Plan, PlanStep

        steps_data = data.get("steps", [])
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
            state.current_plan = Plan(goal=data.get("goal", ""), steps=steps)
        except Exception:
            logger.debug("Plan reconstruction failed", exc_info=True)
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Plan: {len(steps_data)} steps", "cyan")))
    elif etype == "soothe.plan.reflected":
        assessment = data.get("assessment", "")[:60]
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Reflected: {assessment}", "dim italic")))
    elif etype == "soothe.plan.batch_started":
        parallel = data.get("parallel_count", 1)
        if parallel > 1:
            _add_activity(state, Text.assemble(("  . ", "dim"), (f"Batch: {parallel} steps in parallel", "cyan bold")))
    elif etype == "soothe.plan.step_started":
        step_id = data.get("step_id", "")
        index = int(data.get("index", -1))
        description = data.get("description", "")
        if step_id:
            _set_plan_step_status_by_id(state, step_id, "in_progress")
            _add_activity(state, Text.assemble(("  . ", "dim"), (f"Step {step_id}: {description}", "yellow")))
        elif index >= 0:
            _set_plan_step_status(state, index, "in_progress")
            _add_activity(state, Text.assemble(("  . ", "dim"), (f"Step {index + 1}: {description}", "yellow")))
    elif etype == "soothe.plan.step_completed":
        step_id = data.get("step_id", "")
        index = int(data.get("index", -1))
        success = bool(data.get("success", False))
        duration = data.get("duration_ms", 0)
        status = "completed" if success else "failed"
        if step_id:
            _set_plan_step_status_by_id(state, step_id, status)
            dur_str = f" ({duration}ms)" if duration else ""
            label = f"Step {step_id}: {'done' if success else 'failed'}{dur_str}"
        elif index >= 0:
            _set_plan_step_status(state, index, status)
            label = f"Step {index + 1}: {'done' if success else 'failed'}"
        else:
            label = f"Step: {'done' if success else 'failed'}"
        _add_activity(
            state,
            Text.assemble(("  . ", "dim"), (label, "green" if success else "red")),
        )
    elif etype == "soothe.plan.step_failed":
        step_id = data.get("step_id", "")
        error = data.get("error", "")[:80]
        if step_id:
            _set_plan_step_status_by_id(state, step_id, "failed")
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Step {step_id}: FAILED - {error}", "bold red")))
    elif etype == "soothe.goal.batch_started":
        parallel = data.get("parallel_count", 1)
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Goals: {parallel} running in parallel", "cyan bold")))
    elif etype == "soothe.policy.checked":
        verdict = data.get("verdict", "?")
        profile = data.get("profile")
        detail = f"Policy: {verdict}"
        if profile:
            detail += f" (profile={profile})"
        _add_activity(
            state,
            Text.assemble(("  . ", "dim"), (detail, "cyan" if verdict == "allow" else "bold red")),
        )
    elif etype == "soothe.policy.denied":
        reason = data.get("reason", "")
        profile = data.get("profile")
        detail = f"Denied: {reason}"
        if profile:
            detail += f" (profile={profile})"
        _add_activity(state, Text.assemble(("  ! ", "bold red"), (detail, "red")))
    elif etype == "soothe.context.ingested":
        source = data.get("source", "")
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Ingested from {source}", "dim cyan")))
    elif etype == "soothe.thread.created":
        tid = data.get("thread_id", "?")
        state.thread_id = tid
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Thread: {tid}", "dim")))
    elif etype == "soothe.thread.resumed":
        tid = data.get("thread_id", "?")
        state.thread_id = tid
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Resumed thread: {tid}", "dim")))
    elif etype == "soothe.thread.saved":
        tid = data.get("thread_id", state.thread_id or "?")
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Saved thread: {tid}", "dim cyan")))
    elif etype == "soothe.memory.stored":
        memory_id = data.get("id", "?")
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Stored memory: {memory_id}", "cyan")))
    elif etype == "soothe.iteration.started":
        iteration = data.get("iteration", "?")
        goal_desc = _truncate(str(data.get("goal_description", "")), 50)
        _add_activity(
            state,
            Text.assemble(("  >> ", "bold yellow"), (f"Iteration {iteration}: {goal_desc}", "bold yellow")),
        )
    elif etype == "soothe.iteration.completed":
        iteration = data.get("iteration", "?")
        outcome = data.get("outcome", "?")
        duration = data.get("duration_ms", 0)
        style = "green" if outcome == "goal_complete" else "yellow"
        _add_activity(
            state,
            Text.assemble(("  << ", f"bold {style}"), (f"Iteration {iteration}: {outcome} ({duration}ms)", style)),
        )
    elif etype == "soothe.goal.created":
        desc = _truncate(str(data.get("description", "")), 50)
        priority = data.get("priority", "?")
        _add_activity(
            state,
            Text.assemble(("  + ", "bold cyan"), (f"Goal: {desc} (priority={priority})", "cyan")),
        )
    elif etype == "soothe.goal.completed":
        goal_id = data.get("goal_id", "?")
        _add_activity(state, Text.assemble(("  + ", "bold green"), (f"Goal {goal_id} completed", "green")))
    elif etype == "soothe.goal.failed":
        goal_id = data.get("goal_id", "?")
        error = _truncate(str(data.get("error", "")), 50)
        retry = data.get("retry_count", 0)
        _add_activity(
            state,
            Text.assemble(("  ! ", "bold red"), (f"Goal {goal_id} failed (retry {retry}): {error}", "red")),
        )
    elif etype == "soothe.error":
        error = data.get("error", "unknown")
        _add_activity(state, Text.assemble(("  ! ", "bold red"), (error, "red")))
        state.errors.append(error)
    elif etype == "soothe.chitchat.started":
        query = _truncate(str(data.get("query", "")), 50)
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Chitchat: {query}", "dim")))
    elif etype == "soothe.chitchat.response":
        content = data.get("content", "")
        if content and should_show("assistant_text", verbosity):
            state.full_response.append(content)


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

    if etype == "soothe.tool.search.started":
        query = data.get("query", "")
        engines = data.get("engines", [])
        summary = f"Searching: {_truncate(str(query), 40)}"
        if engines:
            summary += f" ({', '.join(engines[:3])})"
        _add_activity(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")))

    elif etype == "soothe.tool.search.completed":
        query = data.get("query", "")
        count = data.get("result_count", 0)
        response_time = data.get("response_time")
        summary = f"Search complete: {count} results"
        if response_time:
            summary += f" ({response_time:.1f}s)"
        _add_activity(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")))

    elif etype == "soothe.tool.search.failed":
        query = data.get("query", "")
        error = data.get("error", "unknown error")
        summary = f"Search failed: {_truncate(str(error), 40)}"
        _add_activity(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")))

    elif etype == "soothe.tool.crawl.started":
        url = data.get("url", "")
        summary = f"Crawling: {_truncate(str(url), 50)}"
        _add_activity(state, Text.assemble(("  ⚙ ", "dim"), (summary, "blue")))

    elif etype == "soothe.tool.crawl.completed":
        url = data.get("url", "")
        content_length = data.get("content_length", 0)
        summary = f"Crawl complete: {content_length} bytes"
        _add_activity(state, Text.assemble(("  ✓ ", "dim green"), (summary, "green")))

    elif etype == "soothe.tool.crawl.failed":
        url = data.get("url", "")
        error = data.get("error", "unknown error")
        summary = f"Crawl failed: {_truncate(str(error), 40)}"
        _add_activity(state, Text.assemble(("  ✗ ", "bold red"), (summary, "red")))


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
    if etype == "soothe.browser.step":
        step = data.get("step", "?")
        action = _truncate(str(data.get("action", "")), 50)
        url = _truncate(str(data.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
    elif etype == "soothe.browser.cdp":
        status = data.get("status", "")
        if status == "connected":
            summary = "Connected to existing browser"
        elif status == "not_found":
            summary = "No existing browser found, launching new"
        else:
            summary = f"Browser CDP: {status}"
    elif etype == "soothe.research.web_search":
        query = data.get("query", "")
        engines = data.get("engines", [])
        summary = f"Searching: {_truncate(str(query), 40)}"
        if engines:
            summary += f" ({', '.join(engines)})"
    elif etype == "soothe.research.search_done":
        count = data.get("result_count", 0)
        summary = f"Found {count} results"
    elif etype == "soothe.research.queries_generated":
        count = data.get("count", 0)
        queries = data.get("queries", [])
        summary = f"Generated {count} search queries"
        if queries and len(queries) <= _MAX_INLINE_QUERIES:
            summary += f": {', '.join(_truncate(str(q), 30) for q in queries[:_MAX_INLINE_QUERIES])}"
    elif etype == "soothe.research.complete":
        summary = "Research completed"
    else:
        # Fallback for any other progress events
        summary = etype.replace("soothe.", "").replace("_", " ").title()

    logger.info("Subagent progress [%s]: %s", tag, summary)
    _add_activity(state, Text.assemble(("  ", ""), (f"[{tag}] ", "cyan"), (summary, "yellow")))


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

    if etype == "soothe.browser.step":
        step = data.get("step", "?")
        action = _truncate(str(data.get("action", "")), 50)
        url = _truncate(str(data.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
    elif etype.startswith("soothe.research."):
        label = etype.replace("soothe.research.", "").replace("_", " ")
        query = data.get("query", data.get("topic", ""))
        summary = label
        if query:
            summary += f": {_truncate(str(query), 40)}"
    elif etype == "soothe.claude.tool_use":
        summary = f"Tool: {data.get('tool', data.get('name', etype))}"
    elif etype == "soothe.claude.text":
        summary = f"Text: {_truncate(str(data.get('text', '')), 50)}"
    elif etype == "soothe.claude.result":
        cost = data.get("cost_usd", 0)
        duration = data.get("duration_ms", 0)
        summary = f"Done (${cost:.4f}, {duration}ms)" if cost else "Done"
    elif etype.startswith("soothe.skillify."):
        summary = etype.replace("soothe.skillify.", "").replace("_", " ")
        detail = data.get("skill", data.get("query", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    elif etype.startswith("soothe.weaver."):
        summary = etype.replace("soothe.weaver.", "").replace("_", " ")
        detail = data.get("agent_name", data.get("task", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    else:
        summary = etype.replace("_", " ")[:50]

    logger.info("Subagent event [%s]: %s", tag, summary)
    logger.debug("Subagent event raw [%s]: %s  data=%s", tag, etype, data)
    _add_activity(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (summary, "dim")))


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
    _add_activity(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (f"Text: {brief}", "dim")))


def _handle_tool_call_activity(
    state: TuiState,
    name: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render tool-call activity line based on verbosity."""
    if not name or not should_show("tool_activity", verbosity):
        return
    if prefix:
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"[{prefix}] [tool] Calling: {name}", "blue")))
    else:
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Calling {name}", "blue")))


def _handle_tool_result_activity(
    state: TuiState,
    tool_name: str,
    content: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render tool-result activity line based on verbosity."""
    if not should_show("tool_activity", verbosity):
        return
    brief = content.replace("\n", " ")[:80]
    if prefix:
        _add_activity(
            state,
            Text.assemble(("  > ", "dim green"), (f"[{prefix}] {tool_name}", "green"), ("  ", ""), (brief, "dim")),
        )
    else:
        _add_activity(state, Text.assemble(("  > ", "dim green"), (tool_name, "green"), ("  ", ""), (brief, "dim")))


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
    _add_activity(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (summary[:80], "dim")))
