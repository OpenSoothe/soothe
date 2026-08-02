"""Pure step-card activity rendering and row classification (RFC-628).

Row model, single-pass index, activity tree, status lines, and step-end
phase transitions. No Textual widget imports — callers pass resolved theme
colors and glyphs; builders return ``Content``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from soothe_sdk.ux.task_namespace import (
    _step_id_from_unified_fragment,
    is_inner_subgraph_task_tool_id,
    is_step_level_task_tool_id,
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
)
from textual.content import Content

from soothe_cli.runtime.presentation.duration_format import format_running_elapsed_compact
from soothe_cli.tui import theme
from soothe_cli.tui.commands.subagent_routing import get_subagent_display_name
from soothe_cli.tui.preview_limits import (
    STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
    TASK_DELEGATION_DESC_MAX_CHARS,
)
from soothe_cli.tui.tool_display import (
    compact_arg_text,
    format_step_tool_activity_command,
    format_step_tool_activity_status_tail,
)

# Todo item status → phase_icon input (IG-664).
_TODO_STATUS_TO_PHASE: dict[str, str] = {
    "pending": "pending",
    "in_progress": "running",
    "completed": "success",
    "done": "success",
    "cancelled": "skipped",
    "canceled": "skipped",
    "failed": "error",
    "error": "error",
}


@dataclass
class StepToolRow:
    """One tool invocation row on the step card (IG-402 / RFC-628).

    Task delegation rows use ``is_task_row=True`` as flat markers. Subgraph tools
    (type ``t``) stay on the step card for per-task counts; they are not rendered
    as nested activity lines (task call line shows the running tool total).
    """

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    phase: str  # pending | running | success | error | rejected | skipped
    output: str = ""
    duration_ms: int = 0
    started_at: float | None = None
    parent_tool_call_id: str | None = None
    is_task_row: bool = False


@dataclass
class StepRowIndex:
    """Single-pass classification of tool rows for one step card.

    Step cards show flat tool rows and task delegation markers. Subgraph tools
    are counted under ``children_by_task`` for the running task-line suffix and
    included in ``total_tool_count``; they are not shown as nested preview lines.
    """

    task_delegations: list[StepToolRow] = field(default_factory=list)
    main_tools: list[StepToolRow] = field(default_factory=list)
    children_by_task: dict[str, list[StepToolRow]] = field(default_factory=dict)
    total_tool_count: int = 0
    main_tool_count: int = 0
    task_delegation_count: int = 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_tool_count_label(count: int, *, singular: str, plural: str) -> str:
    """Human-readable count label, e.g. ``3 tools``."""
    if count <= 0:
        return ""
    word = singular if count == 1 else plural
    return f"{count} {word}"


def count_distinct_tool_call_ids(rows: list[StepToolRow]) -> int:
    """Distinct non-empty tool_call_id values in ``rows``."""
    ids: set[str] = set()
    for row in rows:
        tcid = str(row.tool_call_id).strip()
        if tcid:
            ids.add(tcid)
    return len(ids)


def latest_preview_rows(
    rows: list[StepToolRow],
    limit: int = STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
) -> list[StepToolRow]:
    """Return the most recently appended rows, capped at ``limit``."""
    if not rows:
        return []
    if len(rows) <= limit:
        return list(rows)
    return rows[-limit:]


def stats_title_suffix(index: StepRowIndex) -> str:
    """Step status suffix: total tool count plus task delegation count."""
    parts: list[str] = []
    if index.total_tool_count:
        parts.append(
            format_tool_count_label(index.total_tool_count, singular="tool", plural="tools")
        )
    if index.task_delegation_count:
        parts.append(
            format_tool_count_label(index.task_delegation_count, singular="task", plural="tasks")
        )
    if not parts:
        return ""
    return f" · {', '.join(parts)}"


def compact_step_title_meta(
    *,
    elapsed_secs: int | None,
    tool_count: int,
    task_count: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    retry_attempt: int = 0,
    max_retry_attempts: int = 0,
    format_token: Any = None,
) -> str:
    """Compact middot meta for the step title (IG-664).

    Forms: `` · 45s · 12/1 · ↑8.1K ↓2.0K · ↻1/3``. Description is not truncated;
    callers append this string after the full step brief.
    """
    parts: list[str] = []
    if elapsed_secs is not None:
        parts.append(format_running_elapsed_compact(float(elapsed_secs)))
    if tool_count > 0 or task_count > 0:
        parts.append(f"{max(0, int(tool_count))}/{max(0, int(task_count))}")
    if input_tokens or output_tokens:
        fmt = format_token if callable(format_token) else str
        parts.append(f"↑{fmt(int(input_tokens))} ↓{fmt(int(output_tokens))}")
    if retry_attempt > 0 and max_retry_attempts > 0:
        parts.append(f"↻{int(retry_attempt)}/{int(max_retry_attempts)}")
    if not parts:
        return ""
    return " · " + " · ".join(parts)


def normalize_todo_items(todos: list[Any] | None) -> list[dict[str, str]]:
    """Normalize CoreAgent ``write_todos`` / updates payloads to ``{content, status}``."""
    out: list[dict[str, str]] = []
    if not todos:
        return out
    for item in todos:
        if isinstance(item, dict):
            content = str(item.get("content") or item.get("text") or "").strip()
            status = str(item.get("status") or "pending").strip().lower() or "pending"
            if content:
                out.append({"content": content, "status": status})
        else:
            text = str(item or "").strip()
            if text:
                out.append({"content": text, "status": "pending"})
    return out


def coerce_todos_list(raw: object) -> list[Any] | None:
    """Coerce a ``todos`` field to a list (handles JSON strings from streaming)."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(loaded, list):
            return loaded
    return None


def is_write_todos_tool_name(tool_name: object) -> bool:
    """True for ``write_todos`` / ``WriteTodos`` style names."""
    name = str(tool_name or "").strip()
    if not name:
        return False
    if name == "write_todos":
        return True
    # CamelCase / mixed display forms → snake_case.
    snake = "".join(("_" + c.lower()) if c.isupper() else c for c in name).lstrip("_")
    return snake.replace("-", "_").lower() == "write_todos"


def todo_status_phase(status: str) -> str:
    """Map a todo status string to a ``phase_icon`` phase."""
    return _TODO_STATUS_TO_PHASE.get((status or "pending").strip().lower(), "pending")


def has_task_activity_body(
    index: StepRowIndex,
    subagent_notes: list[str],
    subagent_notes_by_task: dict[str, list[str]],
    todos: list[dict[str, str]] | None = None,
) -> bool:
    """True when the step card should show the task-activity tree panel (IG-513/IG-664)."""
    if todos:
        return True
    if subagent_notes or subagent_notes_by_task:
        return True
    if index.task_delegations:
        return True
    return bool(index.main_tools)


def branched_prose_body(
    body: str,
    *,
    gutter: str,
    circle_empty: str,
    style: str,
) -> Content:
    """Streamed execute-phase prose: tree gutter per line."""
    text = (body or "").rstrip()
    if not text:
        return Content("")
    line_gutter = f"{gutter}{circle_empty} "
    parts: list[object] = []
    for i, ln in enumerate(text.splitlines()):
        if i:
            parts.append("\n")
        parts.append(Content.styled(f"{line_gutter}{ln}", style))
    return Content.assemble(*parts)


def finalize_tool_rows_on_step_end(
    rows: list[StepToolRow],
    task_delegations: list[StepToolRow],
    *,
    success: bool,
) -> None:
    """Finalize open tool rows when the step card completes.

    On successful steps, pending/running/skipped subgraph tools are marked
    ``success`` so task branches show Done instead of Skipped/Pending when
    the subagent finished without per-tool ToolMessage events.
    """
    terminal = "success" if success else "skipped"
    open_phases = ("pending", "running") if not success else ("pending", "running", "skipped")
    for row in rows:
        if row.phase in open_phases:
            row.phase = terminal
            row.started_at = None
    if success:
        for task_row in task_delegations:
            if (task_row.phase or "pending").strip().lower() in (
                "pending",
                "running",
                "skipped",
            ):
                task_row.phase = "success"
                task_row.started_at = None


# ---------------------------------------------------------------------------
# Row classification helpers
# ---------------------------------------------------------------------------


def row_belongs_to_step(row: StepToolRow, step_id: str) -> bool:
    """True when ``row`` belongs to this step card (unified id encodes step)."""
    parsed_sid, _, _, _ = parse_unified_tool_call_id(row.tool_call_id)
    if parsed_sid:
        canonical_step_id = _step_id_from_unified_fragment(step_id)
        return parsed_sid == canonical_step_id
    return True


def is_task_metadata_only_tool_row(row: StepToolRow) -> bool:
    """True when a nested row is task metadata and should stay hidden in branch activity."""
    if is_inner_subgraph_task_tool_id(row.tool_call_id):
        return True
    if (row.tool_name or "").strip() == "task":
        return True
    args = row.args if isinstance(row.args, dict) else {}
    subagent_type = str(args.get("subagent_type") or "").strip()
    desc = str(args.get("description") or args.get("prompt") or "").strip()
    return bool(subagent_type and desc)


def task_delegation_dedupe_key(row: StepToolRow, step_id: str) -> str:
    """Stable key for one main-graph task delegation (aliases share one branch)."""
    tcid = str(row.tool_call_id).strip()
    if not tcid:
        return ""
    if row.is_task_row or is_step_level_task_tool_id(tcid):
        parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
        if parsed_sid and parsed_sid != step_id:
            return tcid
        return normalize_step_task_tool_call_id(step_id, tcid)
    return tcid


def prefer_task_delegation_row(candidate: StepToolRow, incumbent: StepToolRow) -> bool:
    """True when ``candidate`` should replace ``incumbent`` for the same task key."""
    if candidate.is_task_row and not incumbent.is_task_row:
        return True
    if incumbent.is_task_row and not candidate.is_task_row:
        return False
    return len(candidate.args or {}) >= len(incumbent.args or {})


def row_counts_for_main_tools(row: StepToolRow, step_id: str) -> bool:
    """True for main-agent tools on this step (excludes task rows and subgraph tools)."""
    if row.is_task_row:
        return False
    if not row_belongs_to_step(row, step_id):
        return False
    if is_task_metadata_only_tool_row(row):
        return False
    tcid = str(row.tool_call_id).strip()
    if not tcid:
        return False
    if is_step_level_task_tool_id(tcid):
        return False
    _, type_code, _, _ = parse_unified_tool_call_id(tcid)
    if type_code == "t":
        return False
    return True


def row_counts_for_step_tool_total(row: StepToolRow, step_id: str) -> bool:
    """True for rows that belong in the step-card footer tool total (RFC-628).

    Includes main-graph tools (type ``s``) and subgraph tools (type ``t``).
    Task delegation rows and task-metadata-only rows are excluded. Legacy opaque
    ids parented under a task are also excluded.
    """
    if row.is_task_row:
        return False
    if is_task_metadata_only_tool_row(row):
        return False
    if not row_belongs_to_step(row, step_id):
        return False
    tcid = str(row.tool_call_id).strip()
    if not tcid:
        return False
    _, type_code, _, _ = parse_unified_tool_call_id(tcid)
    if type_code in ("s", "t"):
        return True
    return not bool(row.parent_tool_call_id)


def _task_idx_from_task_row(row: StepToolRow) -> int | None:
    """Parse task index from a step-level ``…:s:task:N`` row id."""
    tcid = str(row.tool_call_id).strip()
    if not tcid:
        return None
    _, type_code, _, tool_info = parse_unified_tool_call_id(tcid)
    if type_code != "s":
        return None
    head = (tool_info or "").split(":")[0]
    if head != "task":
        return None
    tail = (tool_info or "").split(":")[-1]
    if tail.isdigit():
        return int(tail)
    return None


def build_children_by_task(
    step_id: str,
    rows: list[StepToolRow],
    task_delegations: list[StepToolRow],
) -> dict[str, list[StepToolRow]]:
    """Group countable subgraph tools under their parent task delegation key."""
    idx_to_key: dict[int, str] = {}
    for task_row in task_delegations:
        key = task_delegation_dedupe_key(task_row, step_id)
        idx = _task_idx_from_task_row(task_row)
        if key and idx is not None:
            idx_to_key[idx] = key
    if not idx_to_key:
        return {}
    children: dict[str, list[StepToolRow]] = {k: [] for k in idx_to_key.values()}
    for row in rows:
        if row.is_task_row or is_task_metadata_only_tool_row(row):
            continue
        if not row_belongs_to_step(row, step_id):
            continue
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            continue
        _, type_code, idx, _ = parse_unified_tool_call_id(tcid)
        if type_code != "t":
            continue
        key = idx_to_key.get(idx)
        if key:
            children[key].append(row)
    return {k: v for k, v in children.items() if v}


def normalized_task_note_key(step_id: str, task_tool_call_id: str) -> str:
    """Normalize task tool_call_id for subagent note lookup."""
    tcid = str(task_tool_call_id).strip()
    if not tcid:
        return ""
    if is_step_level_task_tool_id(tcid):
        return normalize_step_task_tool_call_id(step_id, tcid)
    return tcid


class StepRowClassifier:
    """Builds a :class:`StepRowIndex` from raw tool rows."""

    @staticmethod
    def build(step_id: str, rows: list[StepToolRow]) -> StepRowIndex:
        """Classify rows into task delegations, main tools, and per-task children."""
        task_delegations = StepRowClassifier._iter_task_delegation_rows(step_id, rows)
        main_tools = [r for r in rows if row_counts_for_main_tools(r, step_id)]
        children_by_task = build_children_by_task(step_id, rows, task_delegations)
        countable = [r for r in rows if row_counts_for_step_tool_total(r, step_id)]
        return StepRowIndex(
            task_delegations=task_delegations,
            main_tools=main_tools,
            children_by_task=children_by_task,
            total_tool_count=count_distinct_tool_call_ids(countable),
            main_tool_count=count_distinct_tool_call_ids(main_tools),
            task_delegation_count=len(task_delegations),
        )

    @staticmethod
    def build_orphan(rows: list[StepToolRow], *, task_idx: int = 0) -> StepRowIndex:
        """Classify rows for an intake-only orphan SubAgent card.

        Host stamps wired-subagent tools as ``{step}:s:{id}`` (type ``s``).
        Nested task subgraphs use type ``t`` filtered by ``task_idx``. Both
        belong on the orphan card as primary activity (no task-delegation branch).
        """
        filtered_rows: list[StepToolRow] = []
        for row in rows:
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            if is_task_metadata_only_tool_row(row):
                continue
            _, type_code, idx, _ = parse_unified_tool_call_id(tcid)
            if type_code == "t":
                if idx == task_idx:
                    filtered_rows.append(row)
                continue
            # Type ``s`` (intake wire stamp) or opaque ids → show on orphan card.
            filtered_rows.append(row)

        return StepRowIndex(
            task_delegations=[],
            main_tools=filtered_rows,
            children_by_task={},
            total_tool_count=count_distinct_tool_call_ids(filtered_rows),
            main_tool_count=len(filtered_rows),
            task_delegation_count=0,
        )

    @staticmethod
    def _iter_task_delegation_rows(step_id: str, rows: list[StepToolRow]) -> list[StepToolRow]:
        """Task delegation rows on this step (unified ``{step}:s:task:…`` ids)."""
        by_key: dict[str, StepToolRow] = {}
        canonical_step_id = _step_id_from_unified_fragment(step_id)
        for row in rows:
            if not row.is_task_row and not is_step_level_task_tool_id(row.tool_call_id):
                continue
            parsed_sid, _, _, _ = parse_unified_tool_call_id(str(row.tool_call_id or ""))
            if parsed_sid and parsed_sid != canonical_step_id:
                continue
            key = task_delegation_dedupe_key(row, step_id)
            if not key:
                continue
            prev = by_key.get(key)
            if prev is None or prefer_task_delegation_row(row, prev):
                by_key[key] = row
        return sorted(by_key.values(), key=lambda r: r.tool_call_id)


# ---------------------------------------------------------------------------
# Phase / tone / label helpers
# ---------------------------------------------------------------------------


def phase_icon(
    phase: str,
    g: Any,
    *,
    spinner_position: int = 0,
    animate_running: bool = False,
) -> str:
    """Lifecycle glyph for a task branch or tool row."""
    p = (phase or "pending").strip().lower()
    if p in ("success", "done"):
        return g.checkmark
    if p in ("error", "rejected", "failed"):
        return g.error
    if p == "running" and animate_running:
        frames = g.spinner_frames
        return frames[spinner_position % len(frames)]
    return g.circle_empty


def task_tool_row_tone_for_phase(phase: str, colors: Any) -> str:
    """Textual style for a tool row or task label from lifecycle phase."""
    p = (phase or "pending").strip().lower()
    if p in ("error", "rejected", "failed"):
        return colors.error
    return theme.SECONDARY_TEXT_STYLE


def task_tool_row_tone(row: StepToolRow, colors: Any) -> str:
    """Textual style for a tool row from its lifecycle phase."""
    return task_tool_row_tone_for_phase(row.phase or "pending", colors)


def preview_task_description(
    description: object,
    *,
    max_chars: int = TASK_DELEGATION_DESC_MAX_CHARS,
) -> str:
    """Collapse whitespace and truncate for a single-line task description preview."""
    if isinstance(description, str):
        text = compact_arg_text(description.strip())
    else:
        text = compact_arg_text(str(description or "").strip())
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def subagent_task_label(subagent_type: object, description: object = "") -> str:
    """Display label ``DisplayName(preview)`` for a subagent task description."""
    if isinstance(subagent_type, str):
        st = subagent_type.strip()
    else:
        st = str(subagent_type or "").strip()
    name = get_subagent_display_name(st) if st else "Task"
    desc_text = preview_task_description(description)
    if desc_text:
        return f"{name}({desc_text})"
    return name


def task_delegation_label(task_row: StepToolRow) -> str:
    """Display label ``SubAgentName(description)`` for a task delegation row."""
    args = dict(task_row.args or {})
    return subagent_task_label(
        args.get("subagent_type", ""),
        args.get("description") or args.get("prompt") or "",
    )


def append_tool_activity_lines(
    parts: list[object],
    rows: list[StepToolRow],
    *,
    gutter: str,
    g: Any,
    colors: Any,
    spinner_position: int,
    animate_running: bool,
) -> None:
    """Append capped per-tool activity lines under a task or step branch."""
    for row in rows:
        if parts:
            parts.append("\n")
        phase = (row.phase or "pending").strip().lower()
        icon = phase_icon(
            row.phase or "pending",
            g,
            spinner_position=spinner_position,
            animate_running=animate_running and phase == "running",
        )
        command = format_step_tool_activity_command(row.tool_name, row.args or {})
        tail = format_step_tool_activity_status_tail(
            row.phase or "pending",
            duration_ms=row.duration_ms,
            error=str(row.output or "") if phase == "error" else "",
        )
        tone = task_tool_row_tone(row, colors)
        parts.append(Content.styled(f"{gutter}{icon} {command}{tail}", tone))


# ---------------------------------------------------------------------------
# Status lines
# ---------------------------------------------------------------------------


class StepCardStatusLine:
    """Pure footer status line builders (pending / completed; no Running — IG-664)."""

    @staticmethod
    def footer_pending(
        *,
        gutter: str,
        circle_empty: str,
        stats_suffix: str,
        token_suffix: str = "",
        colors: Any,
    ) -> Content:
        """Step card footer for planned steps not yet executing."""
        head = f"{gutter}{circle_empty} Pending..."
        tail = f"{stats_suffix}{token_suffix}"
        parts: list[object] = [Content.styled(head, colors.cognition)]
        if tail:
            parts.append(Content.styled(tail, theme.SECONDARY_TEXT_STYLE))
        return Content.assemble(*parts)

    @staticmethod
    def footer_completed(
        *,
        gutter: str,
        icon: str,
        head: str,
        suffix: str = "",
        success: bool,
        colors: Any,
    ) -> Content:
        """Step card footer after successful or failed completion."""
        head_tone = theme.SECONDARY_TEXT_STYLE if success else colors.card_error
        parts: list[object] = [Content.styled(f"{gutter}{icon} {head}", head_tone)]
        if suffix:
            parts.append(Content.styled(suffix, theme.SECONDARY_TEXT_STYLE))
        return Content.assemble(*parts)


# Activity tree renderer
# ---------------------------------------------------------------------------


class StepActivityTree:
    """Pure render: To-do + Tool-use sections under the step title (IG-664).

    Task rows are flat markers under Tool-use. While a task is running, the marker
    line shows that task's subgraph tool count. Nested child tool lines are not
    rendered.
    """

    @staticmethod
    def render(
        *,
        step_id: str,
        step_status: str,
        index: StepRowIndex,
        subagent_notes: list[str],
        subagent_notes_by_task: dict[str, list[str]],
        spinner_position: int,
        colors: Any,
        g: Any,
        preview_limit: int = STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
        todos: list[dict[str, str]] | None = None,
    ) -> Content:
        """To-do section then Tool-use section (task markers + main tool preview)."""
        section_gutter = f"{g.output_prefix}  "
        item_gutter = f"{g.output_prefix}    "
        parts: list[object] = []
        todo_items = list(todos or [])

        main_source = list(index.main_tools)
        if todo_items:
            # Avoid duplicating write_todos when the Todo section is live.
            main_source = [r for r in main_source if not is_write_todos_tool_name(r.tool_name)]
        main_preview = latest_preview_rows(main_source, preview_limit)
        has_tools = bool(
            index.task_delegations or main_preview or subagent_notes or subagent_notes_by_task
        )
        if not todo_items and not has_tools:
            return Content("")

        first_block = True
        if todo_items:
            first_block = False
            parts.append(Content.styled(f"{section_gutter}To-do", theme.SECONDARY_TEXT_STYLE))
            for item in todo_items:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                status = str(item.get("status") or "pending")
                phase = todo_status_phase(status)
                animate = phase == "running" and step_status == "running"
                icon = phase_icon(
                    phase,
                    g,
                    spinner_position=spinner_position,
                    animate_running=animate,
                )
                tone = task_tool_row_tone_for_phase(phase, colors)
                parts.append("\n")
                parts.append(Content.styled(f"{item_gutter}{icon} {content}", tone))

        if has_tools:
            if not first_block:
                parts.append("\n")
            first_block = False
            parts.append(Content.styled(f"{section_gutter}Tool-use", theme.SECONDARY_TEXT_STYLE))

            for task_row in index.task_delegations:
                parts.append("\n")
                task_key = task_delegation_dedupe_key(task_row, step_id)
                task_phase = (task_row.phase or "pending").strip().lower()
                if task_phase == "pending" and step_status == "running":
                    task_phase = "running"
                task_icon = phase_icon(
                    task_phase,
                    g,
                    spinner_position=spinner_position,
                    animate_running=task_phase == "running",
                )
                label = task_delegation_label(task_row)
                if task_phase == "running":
                    child_count = count_distinct_tool_call_ids(
                        index.children_by_task.get(task_key, [])
                    )
                    count_label = format_tool_count_label(
                        child_count, singular="tool", plural="tools"
                    )
                    if count_label:
                        label = f"{label} · {count_label}"
                task_tone = task_tool_row_tone_for_phase(task_phase, colors)
                parts.append(
                    Content.styled(
                        f"{item_gutter}{task_icon} {label}",
                        task_tone,
                    )
                )

                for note in subagent_notes_by_task.get(task_key, []):
                    text = (note or "").strip()
                    if not text:
                        continue
                    parts.append("\n")
                    parts.append(Content.styled(f"{item_gutter}{text}", theme.SECONDARY_TEXT_STYLE))

            if main_preview:
                append_tool_activity_lines(
                    parts,
                    main_preview,
                    gutter=item_gutter,
                    g=g,
                    colors=colors,
                    spinner_position=spinner_position,
                    animate_running=step_status == "running",
                )
                hidden_tools = len(main_source) - len(main_preview)
                if hidden_tools > 0:
                    label = f"+{hidden_tools} more tool{'s' if hidden_tools != 1 else ''}"
                    parts.append("\n")
                    parts.append(
                        Content.styled(f"{item_gutter}· {label}", theme.SECONDARY_TEXT_STYLE)
                    )

            for note in subagent_notes:
                t = (note or "").strip()
                if not t:
                    continue
                parts.append("\n")
                parts.append(Content.styled(f"{item_gutter}{t}", theme.SECONDARY_TEXT_STYLE))

        return Content.assemble(*parts) if parts else Content("")
