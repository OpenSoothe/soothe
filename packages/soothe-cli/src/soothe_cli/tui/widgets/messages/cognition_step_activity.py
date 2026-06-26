"""Pure step-card activity rendering and row classification (RFC-628).

Row model, single-pass index, activity tree, status lines, and step-end
phase transitions. No Textual widget imports — callers pass resolved theme
colors and glyphs; builders return ``Content``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

from soothe_sdk.ux.task_namespace import (
    _step_id_from_unified_fragment,
    is_inner_subgraph_task_tool_id,
    is_step_level_task_tool_id,
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
)
from textual.content import Content

from soothe_cli.runtime.presentation.duration_format import format_duration
from soothe_cli.tui.commands.subagent_routing import get_subagent_display_name
from soothe_cli.tui.preview_limits import STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT
from soothe_cli.tui.tool_display import (
    compact_arg_text,
    format_step_tool_activity_command,
    format_step_tool_activity_status_tail,
)
from soothe_cli.tui.widgets.messages._helpers import _MAX_TASK_DELEGATION_DESC_CHARS


@dataclass
class StepToolRow:
    """One tool invocation row on the step card (IG-402, IG-419).

    IG-419: Supports nesting via parent_tool_call_id for inner subagent tools.
    Task delegation rows (is_task_row=True) are parent headers; inner tools
    nest underneath with indentation.
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
    """Single-pass classification of tool rows for one step card (IG-513).

    Simplified for flattened display: step cards show flat tool rows and
    task delegation markers only. SubAgent cards own their own tool rows.
    """

    task_delegations: list[StepToolRow] = field(default_factory=list)
    main_tools: list[StepToolRow] = field(default_factory=list)
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


def tool_stats_title_suffix_for_rows(rows: list[StepToolRow]) -> str:
    """`` · N tools`` suffix for task/main/orphan branches."""
    count = count_distinct_tool_call_ids(rows)
    bare = format_tool_count_label(count, singular="tool", plural="tools")
    return f" · {bare}" if bare else ""


def has_task_activity_body(
    index: StepRowIndex,
    subagent_notes: list[str],
    subagent_notes_by_task: dict[str, list[str]],
) -> bool:
    """True when the step card should show the task-activity tree panel (IG-513)."""
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


def task_idx_from_delegation_row(task_row: StepToolRow) -> int | None:
    """Task index encoded in a step-level ``task`` unified id (``task:0`` → 0)."""
    _, type_code, _, tool_info = parse_unified_tool_call_id(task_row.tool_call_id)
    if type_code != "s":
        return None
    head = (tool_info or "").split(":")[0]
    if head != "task":
        return None
    tail = (tool_info or "").split(":")[-1]
    if tail.isdigit():
        return int(tail)
    return 0


def task_parent_ids_match(step_id: str, parent_id: str, row_parent_id: str) -> bool:
    """True when two tool_call_ids refer to the same step-level task delegation."""
    if not row_parent_id:
        return False
    if row_parent_id == parent_id:
        return True
    if is_step_level_task_tool_id(parent_id) or is_step_level_task_tool_id(row_parent_id):
        p_sid, _, _, _ = parse_unified_tool_call_id(parent_id)
        r_sid, _, _, _ = parse_unified_tool_call_id(row_parent_id)
        if p_sid != step_id or r_sid != step_id:
            return parent_id == row_parent_id
        return normalize_step_task_tool_call_id(
            step_id, row_parent_id
        ) == normalize_step_task_tool_call_id(step_id, parent_id)
    return False


def row_counts_for_main_tools(row: StepToolRow, step_id: str) -> bool:
    """True for main-agent tools on this step (excludes task rows and subgraph tools)."""
    if row.is_task_row:
        return False
    if not row_belongs_to_step(row, step_id):
        return False
    tcid = str(row.tool_call_id).strip()
    if not tcid:
        return False
    if is_step_level_task_tool_id(tcid):
        return False
    _, type_code, _, _ = parse_unified_tool_call_id(tcid)
    if type_code == "t":
        return False
    if row.parent_tool_call_id:
        return False
    return True


def row_counts_for_step_tool_total(row: StepToolRow, step_id: str) -> bool:
    """True for rows that belong in the step-card footer tool total (RFC-628).

    Subgraph tools (type ``t``) belong on SubAgent cards only and are excluded.
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
    return type_code != "t"


def normalized_task_note_key(step_id: str, task_tool_call_id: str) -> str:
    """Normalize task tool_call_id for subagent note lookup."""
    tcid = str(task_tool_call_id).strip()
    if not tcid:
        return ""
    if is_step_level_task_tool_id(tcid):
        return normalize_step_task_tool_call_id(step_id, tcid)
    return tcid


class StepRowClassifier:
    """Builds a :class:`StepRowIndex` from raw tool rows (IG-513 simplified)."""

    @staticmethod
    def build(step_id: str, rows: list[StepToolRow]) -> StepRowIndex:
        """Classify rows into task delegations and main tools (flat display).

        IG-513: Removed children_by_task and orphan_tools — subgraph tools
        route to SubAgent cards, not nested under step card task rows.
        """
        task_delegations = StepRowClassifier._iter_task_delegation_rows(step_id, rows)
        main_tools = [r for r in rows if row_counts_for_main_tools(r, step_id)]
        countable = [r for r in rows if row_counts_for_step_tool_total(r, step_id)]
        return StepRowIndex(
            task_delegations=task_delegations,
            main_tools=main_tools,
            total_tool_count=count_distinct_tool_call_ids(countable),
            main_tool_count=count_distinct_tool_call_ids(main_tools),
            task_delegation_count=len(task_delegations),
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
    if p in ("success", "done"):
        return colors.cognition
    if p in ("error", "rejected", "failed"):
        return colors.error
    if p == "running":
        return colors.cognition
    return colors.muted


def task_tool_row_tone(row: StepToolRow, colors: Any) -> str:
    """Textual style for a tool row from its lifecycle phase."""
    return task_tool_row_tone_for_phase(row.phase or "pending", colors)


def task_delegation_label(task_row: StepToolRow) -> str:
    """Display label ``SubAgentName(description)`` for a task delegation row."""
    args = dict(task_row.args or {})
    raw_type = args.get("subagent_type", "")
    if isinstance(raw_type, str):
        st = raw_type.strip()
    else:
        st = str(raw_type or "").strip()
    name = get_subagent_display_name(st) if st else "Task"
    desc = args.get("description") or args.get("prompt") or ""
    if isinstance(desc, str):
        desc_text = compact_arg_text(desc.strip())
    else:
        desc_text = compact_arg_text(str(desc or "").strip())
    if len(desc_text) > _MAX_TASK_DELEGATION_DESC_CHARS:
        desc_text = desc_text[: _MAX_TASK_DELEGATION_DESC_CHARS - 3].rstrip() + "..."
    if desc_text:
        return f"{name}({desc_text})"
    return name


def touch_task_activity_start(
    task_activity_start_times: dict[str, float],
    task_key: str,
) -> None:
    """Record when subgraph activity began for elapsed-time display."""
    key = str(task_key or "").strip()
    if key and key not in task_activity_start_times:
        task_activity_start_times[key] = time()


def task_delegation_elapsed_suffix(
    task_activity_start_times: dict[str, float],
    task_key: str,
) -> str:
    """Elapsed suffix for a running task branch."""
    start = task_activity_start_times.get(str(task_key or "").strip())
    if start is None:
        return ""
    elapsed_secs = int(time() - start)
    return f" ({format_duration(float(elapsed_secs))})"


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
        )
        tone = task_tool_row_tone(row, colors)
        parts.append(Content.styled(f"{gutter}{icon} {command}{tail}", tone))


# ---------------------------------------------------------------------------
# Status lines
# ---------------------------------------------------------------------------


class StepCardStatusLine:
    """Pure footer and branch status line builders."""

    @staticmethod
    def footer_running(
        *,
        gutter: str,
        spinner_frame: str,
        elapsed_secs: int | None,
        stats_suffix: str,
        token_suffix: str = "",
        retry_suffix: str = "",
        colors: Any,
    ) -> Content:
        """Step card footer while executing."""
        elapsed = ""
        if elapsed_secs is not None:
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        head = f"{gutter}{spinner_frame} Running{retry_suffix}...{elapsed}"
        tail = f"{stats_suffix}{token_suffix}"
        parts: list[object] = [Content.styled(head, colors.warning)]
        if tail:
            parts.append(Content.styled(tail, colors.cognition))
        return Content.assemble(*parts)

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
        line = f"{gutter}{circle_empty} Pending...{stats_suffix}{token_suffix}"
        return Content.styled(line, colors.cognition)

    @staticmethod
    def footer_queued(
        *,
        gutter: str,
        circle_empty: str,
        stats_suffix: str,
        token_suffix: str = "",
        colors: Any,
    ) -> Content:
        """Step card footer for ready steps waiting for a concurrency slot."""
        line = f"{gutter}{circle_empty} Queued...{stats_suffix}{token_suffix}"
        return Content.styled(line, colors.cognition)

    @staticmethod
    def main_branch_running(
        *,
        main_rows: list[StepToolRow],
        branch_gutter: str,
        g: Any,
        colors: Any,
        spinner_position: int,
        step_start_time: float | None,
    ) -> Content:
        """Running status + tool totals for direct main-agent tools."""
        stats_suffix = tool_stats_title_suffix_for_rows(main_rows)
        elapsed = ""
        if step_start_time is not None:
            elapsed_secs = int(time() - step_start_time)
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        frame = phase_icon(
            "running",
            g,
            spinner_position=spinner_position,
            animate_running=True,
        )
        head = f"{branch_gutter}{frame} Running...{elapsed}"
        segs: list[object] = [Content.styled(head, colors.warning)]
        if stats_suffix:
            segs.append(Content.styled(stats_suffix, colors.cognition))
        return Content.assemble(*segs)

    # ---------------------------------------------------------------------------


# Activity tree renderer
# ---------------------------------------------------------------------------


class StepActivityTree:
    """Pure render: task delegation markers and main tool preview (IG-513 simplified).

    IG-513: Removed nested child rendering — subgraph tools route to SubAgent cards.
    Step cards show flat list: task delegation markers + main-agent tools.
    """

    @staticmethod
    def render(
        *,
        step_id: str,
        step_status: str,
        index: StepRowIndex,
        subagent_notes: list[str],
        subagent_notes_by_task: dict[str, list[str]],
        task_activity_start_times: dict[str, float],
        step_start_time: float | None,
        spinner_position: int,
        colors: Any,
        g: Any,
        preview_limit: int = STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
    ) -> Content:
        """Task delegation markers and main tool preview under the step title."""
        branch_gutter = f"{g.output_prefix} "
        parts: list[object] = []
        first_block = True

        main_preview = latest_preview_rows(index.main_tools, preview_limit)
        if (
            not index.task_delegations
            and not main_preview
            and not subagent_notes
            and not subagent_notes_by_task
        ):
            return Content("")

        # IG-513: Task delegations shown as flat markers (no nested children)
        for task_row in index.task_delegations:
            if not first_block:
                parts.append("\n")
            first_block = False
            task_key = task_delegation_dedupe_key(task_row, step_id)
            task_phase = (task_row.phase or "pending").strip().lower()
            # Phase icon for task marker (syncs from SubAgent card on completion)
            task_icon = phase_icon(task_phase, g, animate_running=False)
            label = task_delegation_label(task_row)
            task_tone = task_tool_row_tone_for_phase(task_phase, colors)
            parts.append(
                Content.styled(
                    f"{branch_gutter}{task_icon} {label}",
                    task_tone if task_phase != "pending" else colors.foreground,
                )
            )

            # Per-task subagent notes (from SubAgent card)
            for note in subagent_notes_by_task.get(task_key, []):
                text = (note or "").strip()
                if not text:
                    continue
                parts.append("\n")
                parts.append(Content.styled(f"{branch_gutter}{text}", colors.muted))

        # Main-agent tool preview
        if main_preview:
            first_block = False
            append_tool_activity_lines(
                parts,
                main_preview,
                gutter=branch_gutter,
                g=g,
                colors=colors,
                spinner_position=spinner_position,
                animate_running=step_status == "running",
            )

        # Global subagent notes
        for note in subagent_notes:
            t = (note or "").strip()
            if not t:
                continue
            if not first_block:
                parts.append("\n")
            first_block = False
            parts.append(Content.styled(f"{branch_gutter}{t}", colors.muted))

        return Content.assemble(*parts) if parts else Content("")
