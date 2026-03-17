"""Shared TUI state and rendering helpers used by Textual UI and commands.

This module contains reusable display helpers originally implemented in the
legacy Rich TUI. It is intentionally runtime-agnostic so Textual can reuse the
same plan/activity formatting logic without depending on the legacy UI loop.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from rich.tree import Tree

from soothe.cli.progress_verbosity import ProgressVerbosity, should_show
from soothe.protocols.planner import Plan

logger = logging.getLogger(__name__)

_ACTIVITY_MAX = 300
_MAX_INLINE_QUERIES = 3
_TASK_NAME_RE = re.compile(r'"?name"?\s*:\s*"?(\w+)"?')


_STATUS_MARKERS: dict[str, tuple[str, str]] = {
    "pending": ("[ ]", "dim"),
    "in_progress": ("[>]", "bold yellow"),
    "completed": ("[+]", "bold green"),
    "failed": ("[x]", "bold red"),
}


def extract_text_from_ai_message(msg: Any) -> list[str]:
    """Extract text content from AI messages for conversation logging.

    Handles both LangChain AIMessage objects and deserialized dicts.

    Args:
        msg: Message object (AIMessage or dict).

    Returns:
        List of text strings extracted from the message.
    """
    texts: list[str] = []
    try:
        # Handle LangChain AIMessage objects
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
        elif hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
            texts.append(msg.content)
        # Handle deserialized dict
        elif isinstance(msg, dict):
            blocks = msg.get("content_blocks") or []
            if not blocks:
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    texts.append(content)
            else:
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
    except Exception:
        logger.debug("Failed to extract assistant text", exc_info=True)

    return texts


def render_plan_tree(plan: Plan, title: str | None = None) -> Tree:
    """Render a plan as a Rich Tree with status markers."""
    label = title or f"Plan: {plan.goal}"
    tree = Tree(Text(label, style="bold cyan"))
    for step in plan.steps:
        marker, style = _STATUS_MARKERS.get(step.status, ("[ ]", "dim"))
        step_style = {"in_progress": "yellow", "completed": "green"}.get(step.status, "dim")
        line = Text.assemble(Text(marker, style=style), " ", Text(step.description, style=step_style))
        tree.add(line)
    return tree


@dataclass
class _SubagentState:
    subagent_id: str
    status: str = "running"
    last_activity: str = ""


class SubagentTracker:
    """Tracks per-subagent progress for display."""

    def __init__(self) -> None:
        """Initialize the subagent tracker."""
        self._states: dict[str, _SubagentState] = {}

    def update_from_custom(self, label: str, data: dict[str, Any]) -> None:
        """Update tracker from a subagent custom event."""
        sid = label or "unknown"
        if sid not in self._states:
            self._states[sid] = _SubagentState(subagent_id=sid)
        event_type = data.get("type", "")
        summary = str(data.get("topic", data.get("query", event_type)))[:60]
        self._states[sid].last_activity = summary

    def mark_done(self, sid: str) -> None:
        """Mark a subagent as done."""
        if sid in self._states:
            self._states[sid].status = "done"

    def render(self) -> list[Text]:
        """Return displayable status lines for active subagents."""
        lines: list[Text] = []
        for st in list(self._states.values())[-3:]:
            tag = st.subagent_id.split(":")[-1] if ":" in st.subagent_id else st.subagent_id
            if st.status == "done":
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "green"), ("done", "green")))
            else:
                activity = st.last_activity[:50] or "running..."
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (activity, "yellow")))
        return lines


@dataclass
class TuiState:
    """Mutable display state shared by TUI frontends."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    name_map: dict[str, str] = field(default_factory=dict)
    activity_lines: list[Text] = field(default_factory=list)
    current_plan: Plan | None = None
    subagent_tracker: SubagentTracker = field(default_factory=SubagentTracker)
    seen_message_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    thread_id: str = ""
    last_user_input: str = ""


def _truncate(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _display_subagent_name(name: str) -> str:
    """Return friendly display name for a subagent id."""
    from soothe.cli.commands import SUBAGENT_DISPLAY_NAMES

    return SUBAGENT_DISPLAY_NAMES.get(name.lower(), name.replace("_", " ").title())


def update_name_map_from_tool_calls(message_obj: object, name_map: dict[str, str]) -> None:
    """Update tool-call-id -> display name mapping from AIMessage/tool calls.

    This is the shared implementation used by both TUI and headless modes.
    """
    tool_calls = getattr(message_obj, "tool_calls", None) or []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if tc.get("name") != "task":
            continue
        call_id = str(tc.get("id", ""))
        args = tc.get("args", {})
        raw_name = ""
        if isinstance(args, dict):
            raw_name = str(args.get("agent", "") or args.get("name", ""))
        elif args:
            match = _TASK_NAME_RE.search(str(args))
            if match:
                raw_name = match.group(1)
        if call_id and raw_name:
            name_map[call_id] = _display_subagent_name(raw_name)


def _update_name_map_from_ai_message(state: TuiState, message_obj: object) -> None:
    """Update name mapping from AIMessage (TuiState wrapper)."""
    update_name_map_from_tool_calls(message_obj, state.name_map)


def resolve_namespace_label(namespace: tuple[str, ...], name_map: dict[str, str]) -> str:
    """Resolve namespace tuple to friendly display label.

    This is the shared implementation used by both TUI and headless modes.
    """
    if not namespace:
        return "main"
    parts: list[str] = []
    for segment in namespace:
        seg_str = str(segment)
        if seg_str in name_map:
            parts.append(name_map[seg_str])
        elif seg_str.startswith("tools:"):
            tool_id = seg_str.split(":", 1)[1] if ":" in seg_str else seg_str
            parts.append(name_map.get(tool_id, seg_str))
        else:
            parts.append(seg_str)
    return "/".join(parts)


def _resolve_namespace_label(namespace: tuple[str, ...], state: TuiState) -> str:
    """Resolve namespace tuple to friendly display label (TuiState wrapper)."""
    return resolve_namespace_label(namespace, state.name_map)


def _add_activity(state: TuiState, line: Text) -> None:
    state.activity_lines.append(line)
    logger.info("Activity: %s", line.plain)
    if len(state.activity_lines) > _ACTIVITY_MAX:
        state.activity_lines = state.activity_lines[-_ACTIVITY_MAX:]


def _set_plan_step_status(state: TuiState, index: int, status: str) -> None:
    """Update a plan step status if the current plan exists."""
    if not state.current_plan:
        return
    if 0 <= index < len(state.current_plan.steps):
        state.current_plan.steps[index].status = status


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
        from soothe.protocols.planner import PlanStep

        steps_data = data.get("steps", [])
        try:
            steps = [
                PlanStep(
                    id=s.get("id", str(i)),
                    description=s.get("description", ""),
                    status=s.get("status", "pending"),
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
    elif etype == "soothe.plan.step_started":
        index = int(data.get("index", -1))
        description = data.get("description", "")
        _set_plan_step_status(state, index, "in_progress")
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Step {index + 1}: {description}", "yellow")))
    elif etype == "soothe.plan.step_completed":
        index = int(data.get("index", -1))
        success = bool(data.get("success", False))
        _set_plan_step_status(state, index, "completed" if success else "failed")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Step {index + 1}: {'done' if success else 'failed'}", "green" if success else "red"),
            ),
        )
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
    tag = _resolve_namespace_label(namespace, state) if namespace else "custom"
    etype = str(data.get("type", "custom"))
    summary = str(data.get("message", "")) or str(data.get("topic", "")) or str(data.get("query", "")) or etype
    _add_activity(state, Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (summary[:80], "dim")))
