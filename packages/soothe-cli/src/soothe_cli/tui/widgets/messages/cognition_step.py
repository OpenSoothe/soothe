"""Cognition step message widget."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import monotonic, time
from typing import TYPE_CHECKING, Any

from soothe_sdk.ux.task_namespace import (
    _step_id_from_unified_fragment,
    is_inner_subgraph_task_tool_id,
    is_step_level_task_tool_id,
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
)
from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.widgets import Static

from soothe_cli.runtime.presentation.duration_format import format_duration, format_duration_ms
from soothe_cli.tui import theme
from soothe_cli.tui.commands.subagent_routing import get_subagent_display_name
from soothe_cli.tui.config import get_glyphs, is_ascii_mode
from soothe_cli.tui.preview_limits import (
    STEP_CARD_SHOW_TOOL_ROW_DETAILS,
    STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
    STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD,
)
from soothe_cli.tui.tool_display import (
    compact_arg_text,
    format_step_tool_activity_command,
    format_step_tool_activity_line,
    format_step_tool_activity_status_tail,
)
from soothe_cli.tui.widgets.clipboard import (
    clear_widget_text_selection,
    screen_has_text_selection,
)
from soothe_cli.tui.widgets.messages._helpers import (
    _MAX_TASK_DELEGATION_DESC_CHARS,
    _RUNNING_SPINNER_INTERVAL_SECONDS,
    _STEP_TOOL_PREVIEW_ROWS,
    _assemble_card_header,
    _is_widget_animation_visible,
    _should_refresh_now,
    _strip_success_exit_line,
    request_deferred_tools_refresh,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

logger = logging.getLogger(__name__)


@dataclass
class _StepToolRow:
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
    parent_tool_call_id: str | None = None  # IG-419: Link to parent task row for nesting
    is_task_row: bool = False  # IG-419: Mark as task delegation parent row


class CognitionStepMessage(Vertical):
    """Agent-loop act step card: aggregates main-agent tool calls (IG-402).

    Header is the step description only. Task delegations render in a branch panel
    (``Name(desc)`` plus the latest tool activity lines and nested stats). Footer and
    task-branch status lines show total tool-call counts via :meth:`_stats_title_suffix`
    (e.g. `` · 3 tools, 1 task`` on the step; `` · 6 tools`` under a delegation). The
    status line is always the last
    body line (running, pending, completed, failed). Optional full tool lists use
    ``STEP_CARD_SHOW_TOOL_ROW_DETAILS``. When full tool rows are enabled and exceed
    ``_STEP_TOOL_PREVIEW_ROWS``, click first folds or unfolds the tool list; otherwise
    click toggles whole-card collapse. Subagent notes and execute prose can
    auto-collapse the card body until the user expands it (a new ``set_running`` clears
    that preference).

    Tool rows use the goal-tree gutter (``⎿``) plus hollow/filled circles when shown.
    Prose / notes keep ``⎿ ○`` continuation lines.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionStepMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionStepMessage .step-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionStepMessage .step-status {
        margin-left: 0;
    }

    CognitionStepMessage .step-status.pending {
        color: $cognition;
    }

    CognitionStepMessage .step-status.queued {
        color: $cognition;
    }

    CognitionStepMessage .step-tools {
        margin-left: 0;
        margin-top: 0;
        height: auto;
        color: $text-muted;
    }

    CognitionStepMessage .step-subagent-notes {
        margin-left: 0;
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-detail {
        margin-left: 0;
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-collapse-hint {
        margin-left: 0;
        color: $text-muted;
        background: transparent;
        height: auto;
    }

    CognitionStepMessage.-collapsed .step-tools,
    CognitionStepMessage.-collapsed .step-status,
    CognitionStepMessage.-collapsed .step-subagent-notes,
    CognitionStepMessage.-collapsed .step-detail {
        display: none;
    }

    CognitionStepMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    def __init__(
        self,
        step_id: str,
        description: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._step_id = step_id
        self._description = description.strip()
        self._status = "pending"  # pending | queued | running | success | error
        self._spinner_position = 0
        self._start_time: float | None = None
        self._animation_timer: Timer | None = None
        self._last_rows_animation_refresh: float = 0.0
        # IG-420: Throttling for refresh methods
        self._last_tools_refresh: float | None = None
        self._last_header_refresh: float | None = None
        self._tools_refresh_pending = False
        self._row_cache_key_by_id: dict[str, tuple[Any, ...]] = {}
        self._row_content_by_id: dict[str, Content] = {}
        self._tools_panel_cache_key: tuple[Any, ...] | None = None
        self._status_widget: Static | None = None
        self._header_widget: Static | None = None
        self._tools_widget: Static | None = None
        self._detail_widget: Static | None = None
        self._deferred_complete: tuple[bool, int, int, str] | None = None
        self._deferred_running: bool = False
        self._last_success: bool | None = None
        self._last_duration_ms: int = 0
        self._last_tool_call_count: int = 0
        self._last_summary: str = ""
        self._input_tokens: int = 0
        # IG-504: Retry tracking for running status display
        self._retry_attempt: int = 0
        self._max_retry_attempts: int = 0
        self._retry_error_type: str | None = None
        self._output_tokens: int = 0
        self._interrupt_message: str | None = None
        self._deferred_interrupted: str | None = None
        self._rows: list[_StepToolRow] = []
        self._row_index: dict[str, _StepToolRow] = {}
        self._tools_body_collapsed: bool = False
        self._subagent_notes: list[str] = []
        self._subagent_notes_by_task: dict[str, list[str]] = {}
        self._task_activity_start_times: dict[str, float] = {}
        """Per task-delegation key: monotonic time when subgraph activity began."""
        self._execute_assistant_buffer: str = ""
        self._last_completed_execute_prose: str = ""
        """Execute-step prose frozen when ``set_complete`` runs (TUI dedupe vs goal_completion)."""
        self._card_collapsed: bool = False
        """Whether the entire card body is collapsed (header remains visible)."""
        self._collapse_hint_widget: Static | None = None
        """Widget showing expand/collapse hint text."""
        self._step_card_user_expanded: bool = False
        """If True, skip auto-collapse (user expanded the card body)."""
        self._step_tool_list_user_expanded: bool = False
        """If True, skip auto-folding the tool-row preview (user expanded the list)."""

    def _step_body_line_estimate(self) -> int:
        """Approximate expanded-body line count for auto-collapse."""
        n = len(self._subagent_notes)
        for notes in self._subagent_notes_by_task.values():
            n += len(notes)
        for task_row in self._iter_task_delegation_rows():
            n += 1
            child_rows = self._child_rows_for_task(task_row)
            if child_rows:
                n += 1
                if self._effective_task_delegation_phase(task_row, child_rows) == "running":
                    n += 1
            elif self._status in ("pending", "queued"):
                n += 1
            n += len(self._subagent_notes_by_task.get(str(task_row.tool_call_id).strip(), []))
        if self._status in ("pending", "queued") and not self._iter_task_delegation_rows():
            n += 1
        if STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            n += len(self._rows)
        else:
            for task_row in self._iter_task_delegation_rows():
                child_rows = self._child_rows_for_task(task_row)
                n += min(STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT, len(child_rows))
            main_rows = self._main_agent_tool_rows_for_preview()
            n += min(STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT, len(main_rows))
        buf = (self._execute_assistant_buffer or "").strip()
        if buf:
            n += len(buf.splitlines())
        elif (self._last_completed_execute_prose or "").strip():
            n += len(self._last_completed_execute_prose.splitlines())
        if self._status in ("success", "error"):
            n += 1
        elif self._status == "running":
            n += 1
        return n

    def _maybe_auto_fold_step_tool_list(self) -> None:
        """Fold long tool lists to the preview cap while the step runs (not only after complete)."""
        if not STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            return
        if self._step_tool_list_user_expanded:
            return
        if len(self._rows) <= _STEP_TOOL_PREVIEW_ROWS:
            return
        if self._tools_body_collapsed:
            return
        self._tools_body_collapsed = True

    def _maybe_auto_collapse_step_card(self) -> None:
        if self._step_card_user_expanded:
            return
        if self._step_body_line_estimate() <= STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD:
            return
        if self._card_collapsed:
            return
        self._card_collapsed = True
        self._refresh_collapse_state()

    @property
    def last_completed_execute_prose(self) -> str:
        """Prose accumulated from ``execute_step`` for this step when it completed."""
        return self._last_completed_execute_prose

    def set_description(self, description: str) -> None:
        """Update the step title (full plan/execute brief, no abbreviation)."""
        text = (description or "").strip() or "(step)"
        if text == self._description:
            return
        self._description = text
        self._refresh_header_title()

    def record_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate LLM token usage for this step."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def _token_budget_suffix(self) -> str:
        """Token budget suffix for status lines, e.g. ``in:1.2K out:345``."""
        if not (self._input_tokens or self._output_tokens):
            return ""
        from soothe_cli.runtime.state.session_stats import format_token_count

        parts: list[str] = []
        parts.append(f"in:{format_token_count(self._input_tokens)}")
        parts.append(f"out:{format_token_count(self._output_tokens)}")
        return " · " + " ".join(parts)

    def _step_header_content(self) -> Content:
        return _assemble_card_header(
            self,
            "🚀 ",
            self._description,
        )

    def compose(self) -> ComposeResult:
        yield Static(
            self._step_header_content(),
            classes="step-header",
            id="step-cognition-header",
        )
        yield Static("", classes="step-tools", id="step-cognition-tools", markup=False)
        yield Static(
            "",
            markup=False,
            classes="step-subagent-notes",
            id="step-cognition-subagent-notes",
        )
        yield Static("", classes="step-detail", id="step-cognition-detail")
        yield Static("", classes="step-status", id="step-cognition-status")
        yield Static("", classes="step-collapse-hint", id="step-collapse-hint")

    def on_mount(self) -> None:
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
        self._header_widget = self.query_one("#step-cognition-header", Static)
        self._status_widget = self.query_one("#step-cognition-status", Static)
        self._tools_widget = self.query_one("#step-cognition-tools", Static)
        self._detail_widget = self.query_one("#step-cognition-detail", Static)
        self._collapse_hint_widget = self.query_one("#step-collapse-hint", Static)
        notes = self.query_one("#step-cognition-subagent-notes", Static)
        notes.display = False
        self._status_widget.display = False
        self._tools_widget.display = False
        self._detail_widget.display = False
        self._collapse_hint_widget.display = False
        self._refresh_header_title()
        self._refresh_tools_display()
        self._refresh_collapse_state()
        if self._execute_assistant_buffer.strip() and self._status == "running":
            self._refresh_execute_assistant_running_display()
        if self._deferred_interrupted is not None:
            msg = self._deferred_interrupted
            self._deferred_interrupted = None
            self.set_interrupted(msg)
        elif self._deferred_complete is not None:
            success, duration_ms, tool_call_count, summary = self._deferred_complete
            self._deferred_complete = None
            self.set_complete(success, duration_ms, tool_call_count, summary)
        elif self._deferred_running:
            self._deferred_running = False
            self.set_running()
        elif self._status == "queued":
            self._refresh_queued_display()
        elif self._status == "pending":
            self._refresh_pending_display()

        self._maybe_auto_collapse_step_card()

    def on_click(self, event: Click) -> None:  # noqa: ARG002
        """Toggle tool-row folding or card collapse."""
        event.stop()
        if screen_has_text_selection(self.screen):
            return
        if (
            STEP_CARD_SHOW_TOOL_ROW_DETAILS
            and self._rows
            and len(self._rows) > _STEP_TOOL_PREVIEW_ROWS
        ):
            was_collapsed = self._tools_body_collapsed
            self._tools_body_collapsed = not self._tools_body_collapsed
            if was_collapsed and not self._tools_body_collapsed:
                self._step_tool_list_user_expanded = True
            self._refresh_tools_display()
            return
        has_collapsible_content = (
            (STEP_CARD_SHOW_TOOL_ROW_DETAILS and self._rows)
            or self._has_task_activity_body()
            or self._execute_assistant_buffer.strip()
            or self._status in ("success", "error")
        )
        if has_collapsible_content:
            self.toggle_collapse()

    def toggle_collapse(self) -> None:
        """Toggle the entire card body collapse state."""
        was_collapsed = self._card_collapsed
        self._card_collapsed = not self._card_collapsed
        if was_collapsed and not self._card_collapsed:
            self._step_card_user_expanded = True
        self._refresh_collapse_state()

    def _refresh_collapse_state(self) -> None:
        """Update CSS classes and footer hint based on collapse state."""
        if self._card_collapsed:
            self.add_class("-collapsed")
        else:
            self.remove_class("-collapsed")
        self._sync_step_footer_hint()

    def _sync_step_footer_hint(self) -> None:
        """Single footer line after status: expand card or tool-list affordances.

        Note: The expand/collapse icon is now shown inline in the status line,
        so this widget is hidden for a cleaner design.
        """
        w = self._collapse_hint_widget
        if w is None:
            return
        # Hide the separate hint widget - icon is shown inline in status line
        w.display = False
        # Refresh status line to update the inline expand/collapse icon
        if self._status == "running":
            # Bypass visibility check so tool counts refresh immediately when tool
            # rows repaint (same fix as set_running — do not use _update_running_animation).
            self._sync_running_status_text()
        elif self._status in ("success", "error") and self._detail_widget:
            # Re-apply completion detail with updated icon
            dur_str = format_duration_ms(self._last_duration_ms)
            tool_part = self._status_tool_stats_suffix(self._last_tool_call_count)
            if self._last_success:
                self._update_step_footer_status_line(
                    f"Completed ({dur_str})",
                    success=True,
                    suffix=tool_part,
                )
                prose = (self._last_completed_execute_prose or "").strip()
                if prose and self._detail_widget:
                    self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                    self._detail_widget.display = True
                elif self._detail_widget:
                    self._detail_widget.display = False
            else:
                err_text = self._last_summary.strip() or "Step failed"
                self._update_step_footer_status_line(
                    f"Failed · {dur_str}",
                    success=False,
                )
                self._detail_widget.update(self._step_branched_error_detail(err_text))

    def append_execute_assistant_delta(self, delta: str) -> None:
        """Accumulate per-step LoopAIMessage (``phase=execute_step``) prose into this card."""
        if not delta:
            return
        self._execute_assistant_buffer += delta
        if self._status == "running":
            self._refresh_execute_assistant_running_display()
        self._maybe_auto_collapse_step_card()

    def _refresh_execute_assistant_running_display(self) -> None:
        body = self._execute_assistant_buffer.strip()
        if not body or self._detail_widget is None:
            return
        self._detail_widget.update(self._step_branched_execute_body(body, muted=True))
        self._detail_widget.display = True

    def _has_task_activity_body(self) -> bool:
        """True when the step card should show the task-activity tree panel."""
        if self._subagent_notes or self._subagent_notes_by_task:
            return True
        if self._iter_task_delegation_rows():
            return True
        if self._orphan_subgraph_tool_rows_for_preview():
            return True
        return bool(self._main_agent_tool_rows_for_preview())

    @staticmethod
    def _latest_preview_rows(
        rows: list[_StepToolRow],
        limit: int = STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
    ) -> list[_StepToolRow]:
        """Return the most recently appended rows, capped at ``limit``."""
        if not rows:
            return []
        if len(rows) <= limit:
            return list(rows)
        return rows[-limit:]

    def _main_agent_tool_rows_for_preview(self) -> list[_StepToolRow]:
        """Direct main-agent tool rows (excludes task delegations and subgraph tools)."""
        return [r for r in self._rows if self._row_counts_for_step_status_line(r)]

    def _orphan_subgraph_tool_rows_for_preview(self) -> list[_StepToolRow]:
        """Subgraph tool rows whose parent task delegation row is missing.

        Some streams deliver ``t`` tool rows before/without a visible ``s:task`` row.
        Keep these rows visible on the step card so users still see tool activity.
        """
        task_parent_ids: set[str] = set()
        task_indices: set[int] = set()
        for task_row in self._iter_task_delegation_rows():
            key = self._task_delegation_dedupe_key(task_row)
            if key:
                task_parent_ids.add(key)
            task_idx = self._task_idx_from_delegation_row(task_row)
            if task_idx is not None:
                task_indices.add(task_idx)

        out: list[_StepToolRow] = []
        for row in self._rows:
            if row.is_task_row:
                continue
            if self._is_task_metadata_only_tool_row(row):
                continue
            if not self._row_belongs_to_step(row):
                continue
            tcid = str(row.tool_call_id or "").strip()
            if not tcid:
                continue
            if is_step_level_task_tool_id(tcid) or is_inner_subgraph_task_tool_id(tcid):
                continue
            parsed_sid, type_code, idx, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                continue

            parent_id = str(row.parent_tool_call_id or "").strip()
            if parent_id and is_step_level_task_tool_id(parent_id):
                parent_id = normalize_step_task_tool_call_id(self._step_id, parent_id)
            has_visible_parent = bool(parent_id and parent_id in task_parent_ids)

            # Check if tool would be matched by _child_rows_for_task via unified ID task_idx.
            # Tools with {step}:t{n}:... are matched by task delegation with index n,
            # even without an explicit parent_tool_call_id.
            matched_by_task_idx = type_code == "t" and idx is not None and idx in task_indices

            # Keep unresolved/unparented task-subgraph tool rows visible,
            # but exclude those matched by task_idx (to avoid duplication with child_rows).
            if type_code == "t" and not has_visible_parent and not matched_by_task_idx:
                out.append(row)
        return out

    def _append_tool_activity_lines(
        self,
        parts: list[object],
        rows: list[_StepToolRow],
        *,
        gutter: str,
        g: Any,
        colors: Any,
        animate_running: bool,
    ) -> None:
        """Append capped per-tool activity lines under a task or step branch."""
        for row in rows:
            if parts:
                parts.append("\n")
            phase = (row.phase or "pending").strip().lower()
            icon = self._phase_icon(
                row.phase or "pending",
                g,
                animate_running=animate_running and phase == "running",
            )
            command = format_step_tool_activity_command(row.tool_name, row.args or {})
            tail = format_step_tool_activity_status_tail(
                row.phase or "pending",
                duration_ms=row.duration_ms,
            )
            tone = self._task_tool_row_tone(row, colors)
            parts.append(Content.styled(f"{gutter}{icon} {command}{tail}", tone))

    def _task_delegation_dedupe_key(self, row: _StepToolRow) -> str:
        """Stable key for one main-graph task delegation (aliases share one branch)."""
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return ""
        if row.is_task_row or is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                return tcid
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return tcid

    @staticmethod
    def _prefer_task_delegation_row(candidate: _StepToolRow, incumbent: _StepToolRow) -> bool:
        """True when ``candidate`` should replace ``incumbent`` for the same task key."""
        if candidate.is_task_row and not incumbent.is_task_row:
            return True
        if incumbent.is_task_row and not candidate.is_task_row:
            return False
        return len(candidate.args or {}) >= len(incumbent.args or {})

    def _iter_task_delegation_rows(self) -> list[_StepToolRow]:
        """Task delegation rows on this step (unified ``{step}:s:task:…`` ids)."""
        by_key: dict[str, _StepToolRow] = {}
        for row in self._rows:
            if not row.is_task_row and not is_step_level_task_tool_id(row.tool_call_id):
                continue
            # Skip rows that belong to OTHER steps (parsed step_id != this card's step_id).
            parsed_sid, _, _, _ = parse_unified_tool_call_id(str(row.tool_call_id or ""))
            canonical_step_id = _step_id_from_unified_fragment(self._step_id)
            if parsed_sid and parsed_sid != canonical_step_id:
                continue
            key = self._task_delegation_dedupe_key(row)
            if not key:
                continue
            prev = by_key.get(key)
            if prev is None or self._prefer_task_delegation_row(row, prev):
                by_key[key] = row
        return sorted(by_key.values(), key=lambda r: r.tool_call_id)

    def _task_idx_from_delegation_row(self, task_row: _StepToolRow) -> int | None:
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

    def _task_parent_ids_match(self, parent_id: str, row_parent_id: str) -> bool:
        """True when two tool_call_ids refer to the same step-level task delegation."""
        if not row_parent_id:
            return False
        if row_parent_id == parent_id:
            return True
        if is_step_level_task_tool_id(parent_id) or is_step_level_task_tool_id(row_parent_id):
            p_sid, _, _, _ = parse_unified_tool_call_id(parent_id)
            r_sid, _, _, _ = parse_unified_tool_call_id(row_parent_id)
            if p_sid != self._step_id or r_sid != self._step_id:
                return parent_id == row_parent_id
            return normalize_step_task_tool_call_id(
                self._step_id, row_parent_id
            ) == normalize_step_task_tool_call_id(self._step_id, parent_id)
        return False

    def _is_task_metadata_only_tool_row(self, row: _StepToolRow) -> bool:
        """True when a nested row is task metadata and should stay hidden in branch activity."""
        if is_inner_subgraph_task_tool_id(row.tool_call_id):
            return True
        if (row.tool_name or "").strip() == "task":
            return True
        args = row.args if isinstance(row.args, dict) else {}
        subagent_type = str(args.get("subagent_type") or "").strip()
        desc = str(args.get("description") or args.get("prompt") or "").strip()
        # Some streams emit opaque names/ids (e.g. ``tool-<id>``) for task chunks.
        return bool(subagent_type and desc)

    def _child_rows_for_task(self, task_row: _StepToolRow) -> list[_StepToolRow]:
        """Subgraph tool rows for one task (``parent_tool_call_id`` or ``{step}:t{n}:…``)."""
        raw_parent = str(task_row.tool_call_id).strip()
        parsed_sid, _, _, _ = parse_unified_tool_call_id(raw_parent)
        canonical_step_id = _step_id_from_unified_fragment(self._step_id)
        if parsed_sid and parsed_sid == canonical_step_id:
            parent_id = normalize_step_task_tool_call_id(self._step_id, raw_parent)
        else:
            parent_id = raw_parent
        task_idx = self._task_idx_from_delegation_row(task_row)
        by_id: dict[str, _StepToolRow] = {}
        for row in self._rows:
            if (
                row.is_task_row
                or is_step_level_task_tool_id(row.tool_call_id)
                or self._is_task_metadata_only_tool_row(row)
            ):
                continue
            tcid = str(row.tool_call_id).strip()
            if not tcid:
                continue
            row_parent = str(row.parent_tool_call_id or "").strip()
            if self._task_parent_ids_match(parent_id, row_parent):
                by_id[tcid] = row
                continue
            if task_idx is not None:
                sid, type_code, idx, _ = parse_unified_tool_call_id(tcid)
                if (
                    sid == canonical_step_id
                    and type_code == "t"
                    and idx is not None
                    and idx == task_idx
                ):
                    by_id[tcid] = row
        return sorted(by_id.values(), key=lambda r: r.tool_call_id)

    def _task_delegation_label(self, task_row: _StepToolRow) -> str:
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

    def _phase_icon(self, phase: str, g: Any, *, animate_running: bool = False) -> str:
        """Lifecycle glyph for a task branch or tool row."""
        p = (phase or "pending").strip().lower()
        if p in ("success", "done"):
            return g.checkmark
        if p in ("error", "rejected", "failed"):
            return g.error
        if p == "running" and animate_running:
            frames = g.spinner_frames
            return frames[self._spinner_position % len(frames)]
        return g.circle_empty

    def _task_tool_phase_icon(self, row: _StepToolRow, g: Any) -> str:
        """Glyph for a task-branch tool row from its lifecycle phase."""
        return self._phase_icon(row.phase or "pending", g)

    def _task_tool_status_tail(self, row: _StepToolRow) -> str:
        """Trailing status text for a task-branch tool row (duration, failure, etc.)."""
        phase = (row.phase or "pending").strip().lower()
        if phase == "success" and row.duration_ms > 0:
            return f" ({format_duration_ms(row.duration_ms)})"
        if phase == "error":
            return " · failed"
        if phase == "rejected":
            return " · rejected"
        if phase == "skipped":
            return " · skipped"
        if phase == "running":
            return " · running"
        return ""

    def _task_tool_row_tone(self, row: _StepToolRow, colors: Any) -> str:
        return self._task_tool_row_tone_for_phase(row.phase or "pending", colors)

    def _task_tool_row_tone_for_phase(self, phase: str, colors: Any) -> str:
        p = (phase or "pending").strip().lower()
        if p in ("success", "done"):
            return colors.cognition
        if p in ("error", "rejected", "failed"):
            return colors.error
        if p == "running":
            return colors.cognition
        return colors.muted

    def _task_children_aggregate_phase(self, rows: list[_StepToolRow]) -> str:
        """Aggregate lifecycle phase for nested tools under one task delegation."""
        if not rows:
            return "pending"
        phases = {(r.phase or "pending").strip().lower() for r in rows}
        if "running" in phases:
            return "running"
        if "error" in phases or "rejected" in phases:
            return "failed"
        if phases <= {"success"}:
            return "success"
        if phases <= {"skipped"}:
            return "skipped"
        if "pending" in phases:
            return "pending"
        return "pending"

    def _effective_task_delegation_phase(
        self,
        task_row: _StepToolRow,
        child_rows: list[_StepToolRow],
    ) -> str:
        """Derived phase for a task delegation from its subgraph tool rows."""
        if child_rows:
            phase = self._task_children_aggregate_phase(child_rows)
        else:
            phase = (task_row.phase or "pending").strip().lower()
        # While step is executing with child rows, prevent transient "Done" (success)
        # flashes between tool waves. Only override "success" → "running" (IG-492).
        if self._status == "running" and child_rows and phase == "success":
            return "running"
        if self._status == "success" and phase in ("pending", "running", "skipped"):
            return "success"
        return phase

    def _touch_task_activity_start(self, task_key: str) -> None:
        """Record when subgraph activity began for elapsed-time display."""
        key = str(task_key or "").strip()
        if key and key not in self._task_activity_start_times:
            self._task_activity_start_times[key] = time()

    def _task_delegation_elapsed_suffix(self, task_key: str) -> str:
        start = self._task_activity_start_times.get(str(task_key or "").strip())
        if start is None:
            return ""
        elapsed_secs = int(time() - start)
        return f" ({format_duration(float(elapsed_secs))})"

    def _has_active_task_branch_animation(self) -> bool:
        """True when any task delegation branch needs live spinner/elapsed updates."""
        for task_row in self._iter_task_delegation_rows():
            child_rows = self._child_rows_for_task(task_row)
            if self._effective_task_delegation_phase(task_row, child_rows) == "running":
                return True
        return False

    def _task_children_stats_tone(self, phase: str, colors: Any) -> str:
        p = (phase or "pending").strip().lower()
        if p == "running":
            return colors.cognition
        if p in ("failed", "error", "rejected"):
            return colors.error
        if p == "success":
            return colors.cognition
        return colors.muted

    def _update_step_footer_status_line(
        self,
        head: str,
        *,
        success: bool,
        suffix: str = "",
    ) -> None:
        """Paint the step card footer status (always the last visible body line).

        Args:
            head: The leading status text (e.g. ``"Completed (1.2s)"`` or
                ``"Failed · 1.2s"``) that gets the prominent success/error tone.
            success: Whether this is a successful completion (green) or a
                failure (red).
            suffix: Optional stats tail (tool counts, token budget) that keeps
                the subdued cognition tone so it doesn't drown out the head.
        """
        if self._status_widget is None:
            return
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        icon = g.checkmark if success else g.error
        head_tone = colors.card_success if success else colors.card_error
        suffix_tone = colors.cognition
        self._status_widget.remove_class("pending")
        parts: list[object] = [Content.styled(f"{gutter}{icon} {head}", head_tone)]
        if suffix:
            parts.append(Content.styled(suffix, suffix_tone))
        self._status_widget.update(Content.assemble(*parts))
        self._status_widget.display = True

    @staticmethod
    def _format_tool_count_label(count: int, *, singular: str, plural: str) -> str:
        if count <= 0:
            return ""
        word = singular if count == 1 else plural
        return f"{count} {word}"

    @staticmethod
    def _count_distinct_tool_call_ids(rows: list[_StepToolRow]) -> int:
        ids: set[str] = set()
        for row in rows:
            tcid = str(row.tool_call_id).strip()
            if tcid:
                ids.add(tcid)
        return len(ids)

    def _step_main_tool_count(self) -> int:
        """Distinct main-agent tool calls on this step (excludes task delegations and subgraph)."""
        return self._count_distinct_tool_call_ids(
            [row for row in self._rows if self._row_counts_for_step_status_line(row)]
        )

    def _step_task_delegation_count(self) -> int:
        """Step-level task delegation rows (``{step}:s:task:…``)."""
        return len(self._iter_task_delegation_rows())

    def _tool_stats_suffix_for_rows(self, rows: list[_StepToolRow]) -> str:
        """Total tool-call count for a set of rows (e.g. nested task children)."""
        count = self._count_distinct_tool_call_ids(rows)
        return self._format_tool_count_label(count, singular="tool", plural="tools")

    def _tool_stats_title_suffix_for_rows(self, rows: list[_StepToolRow]) -> str:
        """`` · N tools`` suffix for task/main branches (matches step footer running line)."""
        bare = self._tool_stats_suffix_for_rows(rows)
        return f" · {bare}" if bare else ""

    def _main_branch_status_line(
        self,
        *,
        main_rows: list[_StepToolRow],
        branch_gutter: str,
        g: Any,
        colors: Any,
    ) -> Content:
        """Running status + tool totals for direct main-agent tools (no task delegation)."""
        stats_suffix = self._tool_stats_title_suffix_for_rows(main_rows)
        elapsed = ""
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        frame = self._phase_icon("running", g, animate_running=True)
        head = f"{branch_gutter}{frame} Running...{elapsed}"
        segs: list[object] = [Content.styled(head, colors.warning)]
        if stats_suffix:
            segs.append(Content.styled(stats_suffix, colors.cognition))
        return Content.assemble(*segs)

    def _task_branch_status_line(
        self,
        *,
        phase: str,
        child_rows: list[_StepToolRow],
        task_key: str,
        child_gutter: str,
        g: Any,
        colors: Any,
    ) -> Content:
        """Build one status line for a task delegation branch (footer-aligned format).

        Head (status word + elapsed) gets a phase-specific tone (amber for
        running, green for done, red for failed); the stats suffix stays in the
        subdued ``colors.cognition`` tone so it does not drown out the head.
        """
        stats_suffix = self._tool_stats_title_suffix_for_rows(child_rows)
        p = (phase or "pending").strip().lower()
        if p == "running":
            elapsed = self._task_delegation_elapsed_suffix(task_key)
            frame = self._phase_icon("running", g, animate_running=True)
            head = f"{child_gutter}{frame} Running...{elapsed}"
            segs: list[object] = [Content.styled(head, colors.warning)]
            if stats_suffix:
                segs.append(Content.styled(stats_suffix, colors.cognition))
            return Content.assemble(*segs)
        icon = self._phase_icon(p, g, animate_running=False)
        status_word = {
            "success": "Done",
            "done": "Done",
            "failed": "Failed",
            "error": "Failed",
            "rejected": "Failed",
            "skipped": "Skipped",
            "pending": "Pending",
        }.get(p, "Pending")
        head_tone = {
            "success": colors.card_success,
            "done": colors.card_success,
            "failed": colors.card_error,
            "error": colors.card_error,
            "rejected": colors.card_error,
        }.get(p, self._task_children_stats_tone(p, colors))
        head = f"{child_gutter}{icon} {status_word}"
        segs = [Content.styled(head, head_tone)]
        if stats_suffix:
            segs.append(Content.styled(stats_suffix, colors.cognition))
        return Content.assemble(*segs)

    def _normalized_task_note_key(self, task_tool_call_id: str) -> str:
        tcid = str(task_tool_call_id).strip()
        if not tcid:
            return ""
        if is_step_level_task_tool_id(tcid):
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return tcid

    def _step_task_activity_content(self) -> Content:
        """Task delegations, latest tool activity lines, and notes under the step title."""
        g = get_glyphs()
        branch_gutter = f"{g.output_prefix} "
        child_gutter = f"{g.output_prefix}   "
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        parts: list[object] = []
        first_block = True

        task_rows = self._iter_task_delegation_rows()
        main_rows_all = [r for r in self._rows if self._row_counts_for_step_status_line(r)]
        main_preview = self._latest_preview_rows(self._main_agent_tool_rows_for_preview())
        orphan_preview = self._latest_preview_rows(self._orphan_subgraph_tool_rows_for_preview())
        if not task_rows and not main_preview and not orphan_preview and not self._subagent_notes:
            if not self._subagent_notes_by_task:
                return Content("")

        for task_row in task_rows:
            if not first_block:
                parts.append("\n")
            first_block = False
            task_key = self._task_delegation_dedupe_key(task_row)
            child_rows = self._child_rows_for_task(task_row)
            eff_phase = self._effective_task_delegation_phase(task_row, child_rows)
            if eff_phase == "running" and task_key:
                self._touch_task_activity_start(task_key)

            task_icon = self._phase_icon(eff_phase, g, animate_running=False)
            label = self._task_delegation_label(task_row)
            task_tone = self._task_tool_row_tone_for_phase(eff_phase, colors)
            parts.append(
                Content.styled(
                    f"{branch_gutter}{task_icon} {label}",
                    task_tone if eff_phase != "pending" else colors.foreground,
                )
            )

            child_preview = self._latest_preview_rows(child_rows)
            if child_preview:
                self._append_tool_activity_lines(
                    parts,
                    child_preview,
                    gutter=child_gutter,
                    g=g,
                    colors=colors,
                    animate_running=eff_phase == "running",
                )

            if child_rows:
                status_line = self._task_branch_status_line(
                    phase=eff_phase,
                    child_rows=child_rows,
                    task_key=task_key,
                    child_gutter=child_gutter,
                    g=g,
                    colors=colors,
                )
                parts.append("\n")
                parts.append(status_line)
            elif eff_phase == "running":
                elapsed = self._task_delegation_elapsed_suffix(task_key)
                frame = self._phase_icon("running", g, animate_running=True)
                head = f"{child_gutter}{frame} Running...{elapsed}"
                parts.append("\n")
                parts.append(Content.styled(head, colors.warning))
            elif self._status in ("pending", "queued"):
                wait_word = "Queued..." if self._status == "queued" else "Pending..."
                parts.append("\n")
                parts.append(
                    Content.styled(
                        f"{child_gutter}{g.circle_empty} {wait_word}",
                        colors.muted,
                    )
                )

            for note in self._subagent_notes_by_task.get(task_key, []):
                text = (note or "").strip()
                if not text:
                    continue
                parts.append("\n")
                parts.append(Content.styled(f"{child_gutter}{text}", colors.muted))

        if main_preview:
            # ``_append_tool_activity_lines`` already inserts a leading ``\\n`` when
            # ``parts`` is non-empty; do not add a second separator (blank line).
            first_block = False
            self._append_tool_activity_lines(
                parts,
                main_preview,
                gutter=branch_gutter,
                g=g,
                colors=colors,
                animate_running=self._status == "running",
            )

        if main_rows_all and not task_rows and self._status == "running":
            if not first_block:
                parts.append("\n")
            first_block = False
            parts.append(
                self._main_branch_status_line(
                    main_rows=main_rows_all,
                    branch_gutter=branch_gutter,
                    g=g,
                    colors=colors,
                )
            )

        if orphan_preview:
            first_block = False
            self._append_tool_activity_lines(
                parts,
                orphan_preview,
                gutter=branch_gutter,
                g=g,
                colors=colors,
                animate_running=self._status == "running",
            )

        for note in self._subagent_notes:
            t = (note or "").strip()
            if not t:
                continue
            if not first_block:
                parts.append("\n")
            first_block = False
            parts.append(Content.styled(f"{branch_gutter}{t}", colors.muted))

        return Content.assemble(*parts) if parts else Content("")

    def _refresh_task_activity_display(self) -> None:
        """Repaint the task-activity tree under the step header."""
        show = self._has_task_activity_body()
        try:
            w = self.query_one("#step-cognition-subagent-notes", Static)
        except Exception:  # noqa: BLE001
            if show:
                self._maybe_auto_collapse_step_card()
            return
        if show:
            w.update(self._step_task_activity_content())
            w.display = True
        else:
            w.display = False
        self._maybe_auto_collapse_step_card()

    def append_subagent_activity(
        self,
        line: str,
        *,
        task_tool_call_id: str | None = None,
    ) -> None:
        """Append prose or metadata for a delegated task (optional unified parent id)."""
        text = (line or "").strip()
        if not text:
            return
        task_key = self._normalized_task_note_key(task_tool_call_id or "")
        if task_key:
            self._subagent_notes_by_task.setdefault(task_key, []).append(text)
        else:
            self._subagent_notes.append(text)
        self._refresh_task_activity_display()

    def _row_belongs_to_step(self, row: _StepToolRow) -> bool:
        """True when ``row`` belongs to this step card (unified id encodes step)."""
        parsed_sid, _, _, _ = parse_unified_tool_call_id(row.tool_call_id)
        if parsed_sid:
            # Normalize both step IDs to canonical format (hyphen) for comparison
            # parsed_sid is already canonical from parse_unified_tool_call_id
            # self._step_id may be in wire format (underscore) or canonical (hyphen)
            canonical_step_id = _step_id_from_unified_fragment(self._step_id)
            return parsed_sid == canonical_step_id
        return True

    def _row_counts_for_step_status_line(self, row: _StepToolRow) -> bool:
        """True for main-agent tools on this step (excludes task rows and all subgraph tools)."""
        if row.is_task_row:
            return False
        if not self._row_belongs_to_step(row):
            return False
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return False
        if is_step_level_task_tool_id(tcid):
            return False
        # Exclude all subgraph tools (type_code "t") from main-agent stats.
        # Orphan subgraph tools are handled separately in _orphan_subgraph_tool_rows_for_preview
        # to avoid duplication between main_preview and orphan_preview.
        _, type_code, _, _ = parse_unified_tool_call_id(tcid)
        if type_code == "t":
            return False
        # Exclude tools with a known parent delegation (nested subgraph tools).
        if row.parent_tool_call_id:
            return False
        return True

    def _rebuild_tool_stats(self) -> None:
        """Refresh status lines after tool row changes."""
        self._refresh_task_activity_display()

    def _stats_title_suffix(self) -> str:
        """Step status suffix: main-agent tool totals plus task delegation totals."""
        parts: list[str] = []
        main_count = self._step_main_tool_count()
        task_count = self._step_task_delegation_count()
        if main_count:
            parts.append(self._format_tool_count_label(main_count, singular="tool", plural="tools"))
        if task_count:
            parts.append(self._format_tool_count_label(task_count, singular="task", plural="tasks"))
        if not parts:
            return ""
        return f" · {', '.join(parts)}"

    def _status_tool_stats_suffix(self, fallback_count: int = 0) -> str:
        """Tracked main/task totals for status lines; server total when rows were not tracked."""
        suffix = self._stats_title_suffix()
        if suffix:
            return suffix
        if fallback_count > 0:
            return f" · {fallback_count} tools"
        return ""

    def _refresh_header_title(self) -> None:
        if self._header_widget is None:
            return
        self._header_widget.update(self._step_header_content())

    def _step_goal_tree_gutter(self) -> str:
        """Left column matching :meth:`CognitionGoalTreeMessage._indent_prefix`."""
        return f"{get_glyphs().output_prefix} "

    def _row_to_content(self, row: _StepToolRow) -> Content:
        """One CLI-style tool activity row for the optional full tools panel."""
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        phase = (row.phase or "pending").strip().lower()
        icon = self._phase_icon(
            row.phase or "pending",
            g,
            animate_running=phase == "running",
        )
        body = format_step_tool_activity_line(
            row.tool_name,
            row.args or {},
            row.phase or "pending",
            duration_ms=row.duration_ms,
        )
        tone = self._task_tool_row_tone(row, colors)
        return Content.styled(f"{gutter}{icon} {body}", tone)

    def _step_branched_execute_body(self, body: str, *, muted: bool = True) -> Content:
        """Streamed execute-phase prose: tree gutter per line."""
        g = get_glyphs()
        gutter = f"{g.output_prefix} {g.circle_empty} "
        text = (body or "").rstrip()
        if not text:
            return Content("")
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        style = colors.muted if muted else colors.success
        parts: list[object] = []
        for i, ln in enumerate(text.splitlines()):
            if i:
                parts.append("\n")
            parts.append(Content.styled(f"{gutter}{ln}", style))
        return Content.assemble(*parts)

    def _step_branched_completion_detail(
        self,
        *,
        success: bool,
        status_line_body: str,
        prose: str,
    ) -> Content:
        """Completed step detail: first line ``⎿ ✓|✗ status``; prose lines ``⎿ ○ …``."""
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        icon = g.checkmark if success else g.error
        # Match running step line and tool activity: cognition accent, not semantic green.
        tone = colors.cognition if success else colors.error
        parts: list[object] = [
            Content.styled(f"{gutter}{icon} {status_line_body}", tone),
        ]
        prose = (prose or "").strip()
        if prose:
            sub = f"{g.output_prefix} {g.circle_empty} "
            prose_style = colors.muted if success else tone
            parts.append("\n")
            for i, ln in enumerate(prose.splitlines()):
                if i:
                    parts.append("\n")
                parts.append(Content.styled(f"{sub}{ln}", prose_style))
        return Content.assemble(*parts)

    def _step_branched_error_detail(self, err_text: str) -> Content:
        """Multiline error body: first line ``⎿ ✗ …``; continuations ``⎿ ○ …``."""
        g = get_glyphs()
        gutter = self._step_goal_tree_gutter()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        raw = (err_text or "").strip()
        if not raw:
            return Content("")
        lines = raw.splitlines()
        parts: list[object] = []
        for i, ln in enumerate(lines):
            if i:
                parts.append("\n")
            if i == 0:
                parts.append(Content.styled(f"{gutter}{g.error} {ln}", colors.error))
            else:
                sub = f"{g.output_prefix} {g.circle_empty} "
                parts.append(Content.styled(f"{sub}{ln}", colors.error))
        return Content.assemble(*parts)

    def _build_nested_row_order(self) -> list[_StepToolRow]:
        """Build ordered list: task rows followed by their nested children (IG-419).

        Inner subagent tools (with parent_tool_call_id) appear indented under
        their parent task delegation row. Non-task, non-child rows appear at end.
        """
        task_rows = [r for r in self._rows if r.is_task_row]
        child_by_parent: dict[str, list[_StepToolRow]] = {}
        other_rows: list[_StepToolRow] = []

        for r in self._rows:
            if r.is_task_row:
                continue
            if r.parent_tool_call_id:
                child_by_parent.setdefault(r.parent_tool_call_id, []).append(r)
            else:
                other_rows.append(r)

        result: list[_StepToolRow] = []
        for task_row in task_rows:
            result.append(task_row)
            children = child_by_parent.get(task_row.tool_call_id, [])
            # Sort children by tool_call_id to maintain order
            children.sort(key=lambda x: x.tool_call_id)
            result.extend(children)

        # Append remaining non-task rows at the end
        result.extend(other_rows)
        return result

    def request_tools_display_refresh(self, *, immediate: bool = False) -> None:
        """Queue or run a tool-list repaint (batched across cards during streaming)."""
        if immediate:
            self._tools_refresh_pending = False
            self._refresh_tools_display(force=True)
            return
        self._tools_refresh_pending = True
        request_deferred_tools_refresh(self)

    def _flush_deferred_tools_refresh(self) -> None:
        if not self._tools_refresh_pending:
            return
        self._tools_refresh_pending = False
        self._refresh_tools_display(force=False)

    def _row_content_cache_key(self, row: _StepToolRow) -> tuple[Any, ...]:
        args_key: tuple[tuple[str, Any], ...] = ()
        if row.args:
            try:
                args_key = tuple(sorted((str(k), v) for k, v in row.args.items()))
            except TypeError:
                args_key = (repr(row.args),)
        return (
            row.tool_call_id,
            row.phase,
            row.tool_name,
            row.duration_ms,
            row.output,
            args_key,
            row.parent_tool_call_id,
            row.is_task_row,
        )

    def _refresh_tools_display(self, *, force: bool = False) -> None:
        # IG-420: When widget not mounted, always run auto-collapse checks (no throttling)
        if self._tools_widget is None:
            self._maybe_auto_fold_step_tool_list()
            self._maybe_auto_collapse_step_card()
            self._sync_running_status_line()
            return
        if not STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            self._sync_running_status_line()
            return
        # IG-420: Throttle refreshes to prevent UI lag during streaming (only when mounted)
        if not force and not _should_refresh_now(self._last_tools_refresh):
            return
        self._last_tools_refresh = monotonic()
        if not self._rows:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            return
        self._maybe_auto_fold_step_tool_list()
        self._tools_widget.display = True
        ordered_rows = self._build_nested_row_order()
        show_all = len(ordered_rows) <= _STEP_TOOL_PREVIEW_ROWS or not self._tools_body_collapsed
        visible = ordered_rows if show_all else ordered_rows[:_STEP_TOOL_PREVIEW_ROWS]
        panel_key: tuple[Any, ...] = (
            tuple(self._row_content_cache_key(r) for r in visible),
            show_all,
            self._tools_body_collapsed,
        )
        if not force and panel_key == self._tools_panel_cache_key:
            self._maybe_auto_collapse_step_card()
            self._sync_step_footer_hint()
            return
        lines: list[Content] = []
        for row in visible:
            rk = self._row_content_cache_key(row)
            if self._row_cache_key_by_id.get(row.tool_call_id) != rk:
                content = self._row_to_content(row)
                self._row_cache_key_by_id[row.tool_call_id] = rk
                self._row_content_by_id[row.tool_call_id] = content
            lines.append(self._row_content_by_id[row.tool_call_id])
        self._tools_panel_cache_key = panel_key
        self._tools_widget.update(Content("\n").join(lines))

        self._maybe_auto_collapse_step_card()
        self._sync_step_footer_hint()

    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        raw_args: str = "",
        parent_tool_call_id: str | None = None,  # IG-419
        is_task_row: bool = False,  # IG-419
    ) -> None:
        """Register a new tool row (pending).

        Args:
            tool_call_id: Unique tool call identifier.
            tool_name: Tool name for display.
            args: Parsed tool arguments.
            raw_args: Raw JSON args string from streaming (stored on the row for
                later merge when args arrive incrementally).
            parent_tool_call_id: IG-419: Link to parent task row for nesting.
            is_task_row: IG-419: Mark as task delegation parent row.
        """
        tcid = str(tool_call_id).strip()
        if not tcid:
            return
        # Only main-graph step-level ``task`` delegations are parent rows. Subgraph
        # ``{step}:t{n}:task:…`` streams must stay nested children (or be skipped).
        if not is_task_row and parent_tool_call_id is None:
            _, type_code, _, _ = parse_unified_tool_call_id(tcid)
            if is_step_level_task_tool_id(tcid) or (
                (tool_name or "").strip() == "task" and type_code != "t"
            ):
                is_task_row = True
        if is_task_row and is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                is_task_row = False
            else:
                canonical_tcid = normalize_step_task_tool_call_id(self._step_id, tcid)
                for existing_id, existing_row in list(self._row_index.items()):
                    if self._task_delegation_dedupe_key(existing_row) != canonical_tcid:
                        continue
                    if existing_id == canonical_tcid:
                        self.update_tool_args(canonical_tcid, args)
                        return
                    self._migrate_tool_row_id(existing_id, canonical_tcid)
                    self.update_tool_args(canonical_tcid, args)
                    return
                tcid = canonical_tcid
        if tcid in self._row_index:
            self.update_tool_args(tcid, args)
            return
        row_args: dict[str, Any] = dict(args or {})
        if not row_args and raw_args:
            # Subgraph rows often arrive before namespace binding with only raw JSON.
            # Parse once so task-branch activity can render arguments immediately.
            try:
                loaded = json.loads(raw_args)
            except (TypeError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict

                parsed_from_raw = extract_tool_args_dict(loaded)
                if parsed_from_raw:
                    row_args.update(parsed_from_raw)
        if raw_args:
            row_args["_raw"] = raw_args
        row = _StepToolRow(
            tool_call_id=tcid,
            tool_name=(tool_name or "tool").strip() or "tool",
            args=row_args,
            phase="pending",
            parent_tool_call_id=parent_tool_call_id,
            is_task_row=is_task_row,
        )
        if not is_task_row:
            _, type_code, task_idx, _ = parse_unified_tool_call_id(tcid)
            is_subgraph_tool = type_code == "t" or bool(parent_tool_call_id)
            if is_subgraph_tool:
                row.phase = "running"
                row.started_at = time()
                parent_key = ""
                if parent_tool_call_id:
                    parent_key = self._normalized_task_note_key(parent_tool_call_id)
                elif task_idx is not None:
                    for task_row in self._iter_task_delegation_rows():
                        if self._task_idx_from_delegation_row(task_row) == task_idx:
                            parent_key = self._task_delegation_dedupe_key(task_row)
                            break
                if parent_key:
                    self._touch_task_activity_start(parent_key)
        self._rows.append(row)
        self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._promote_pending_to_running_if_needed()
        # Paint footer stats before heavier tool-list / activity repaints.
        self._sync_running_status_line()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)
        self._refresh_task_activity_display()

    def _promote_pending_to_running_if_needed(self) -> None:
        """Show running UI when tools arrive before ``step.started`` (mounted cards)."""
        if self._status != "pending":
            return
        if getattr(self, "is_mounted", False):
            self.set_running()
            return
        self._status = "running"
        self._start_time = time()
        self._deferred_running = True

    def _canonical_task_lookup_key(self, tool_call_id: str) -> str | None:
        """Normalized task row key when ``tool_call_id`` denotes a step-level delegation."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return None
        if is_step_level_task_tool_id(tcid):
            parsed_sid, _, _, _ = parse_unified_tool_call_id(tcid)
            if parsed_sid and parsed_sid != self._step_id:
                return None
            return normalize_step_task_tool_call_id(self._step_id, tcid)
        return None

    def has_tool_call_row(self, tool_call_id: str) -> bool:
        """Return True if this step card already tracks ``tool_call_id`` (or its task alias)."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return False
        if tcid in self._row_index:
            return True
        task_key = self._canonical_task_lookup_key(tcid)
        if not task_key:
            return False
        if task_key in self._row_index:
            return True
        return any(
            self._task_delegation_dedupe_key(row) == task_key for row in self._row_index.values()
        )

    def _migrate_tool_row_id(self, old_id: str, new_id: str) -> None:
        """Rename a tracked tool row (e.g. provider id → unified step task id)."""
        old = str(old_id).strip()
        new = str(new_id).strip()
        if not old or not new or old == new:
            return
        row = self._row_index.pop(old, None)
        if row is None:
            return
        row.tool_call_id = new
        self._row_index[new] = row
        self._rows = [row if r.tool_call_id == old else r for r in self._rows]
        cache = self._row_content_by_id.pop(old, None)
        if cache is not None:
            self._row_content_by_id[new] = cache
        cache_key = self._row_cache_key_by_id.pop(old, None)
        if cache_key is not None:
            self._row_cache_key_by_id[new] = cache_key

    def pop_tool_row(self, tool_call_id: str) -> _StepToolRow | None:
        """Remove and return a tool row so another step card can adopt it (parallel routing)."""
        tcid = str(tool_call_id).strip()
        if not tcid:
            return None
        row = self._row_index.pop(tcid, None)
        if row is None:
            return None
        self._rows = [r for r in self._rows if r.tool_call_id != tcid]
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)

    def ingest_tool_row(self, row: _StepToolRow) -> None:
        """Attach a tool row moved from another step card."""
        tcid = str(row.tool_call_id).strip()
        if not tcid:
            return
        if tcid in self._row_index:
            self.update_tool_args(tcid, row.args)
            return
        self._rows.append(row)
        self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._promote_pending_to_running_if_needed()
        self._sync_running_status_line()
        self._refresh_header_title()
        self.request_tools_display_refresh(immediate=True)

    def row_duration_ms_since_started(self, tool_call_id: str) -> int:
        """Elapsed ms since this row entered running state (for result lines)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.started_at is None:
            return 0
        return int((time() - row.started_at) * 1000)

    def update_tool_args(self, tool_call_id: str, args: dict[str, Any]) -> None:
        """Refresh kwargs when streaming fills in arguments."""
        from soothe_cli.runtime.parse.message_processing import extract_tool_args_dict
        from soothe_cli.runtime.parse.tool_call_resolution import tool_args_meaningful

        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        incoming = extract_tool_args_dict(args or {})
        merged = dict(row.args or {})
        if incoming:
            merged.update(incoming)
        explicit_args = {
            k: v for k, v in merged.items() if k not in {"_raw", "_subgraph_tool", "value"}
        }
        if explicit_args:
            # Once explicit args arrive, stale placeholder ``_raw`` should not shadow them.
            merged.pop("_raw", None)
        else:
            parsed_from_raw = extract_tool_args_dict({"_raw": merged.get("_raw", "")})
            if parsed_from_raw:
                merged.update(parsed_from_raw)
        if not tool_args_meaningful(merged):
            return
        if merged == row.args:
            return
        row.args = merged
        self._rebuild_tool_stats()
        self._refresh_task_activity_display()
        self._sync_running_status_line()
        self.request_tools_display_refresh()

    def set_tool_running(self, tool_call_id: str) -> None:
        """Mark a tool row as executing (after approval)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.phase not in ("pending", "running"):
            return
        row.phase = "running"
        row.started_at = time()
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_success(self, tool_call_id: str, result: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as success."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "success"
        row.output = _strip_success_exit_line(result)
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_error(self, tool_call_id: str, error: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as error."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "error"
        row.output = error
        row.duration_ms = duration_ms
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_rejected(self, tool_call_id: str) -> None:
        """Mark a tool row as rejected."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "rejected"
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def set_tool_skipped(self, tool_call_id: str) -> None:
        """Mark a tool row skipped (batch reject / incomplete)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "skipped"
        row.started_at = None
        self._refresh_task_activity_display()
        self.request_tools_display_refresh(immediate=True)

    def mark_unfinished_tools_skipped(self) -> None:
        """Mark pending/running rows skipped when the step ends without results."""
        self.mark_unfinished_tools_on_step_complete(success=False)

    def mark_unfinished_tools_on_step_complete(self, *, success: bool) -> None:
        """Finalize open tool rows when the step card completes.

        On successful steps, pending/running/skipped subgraph tools are marked
        ``success`` so task branches show Done instead of Skipped/Pending when
        the subagent finished without per-tool ToolMessage events.
        """
        terminal = "success" if success else "skipped"
        open_phases = ("pending", "running") if not success else ("pending", "running", "skipped")
        for row in self._rows:
            if row.phase in open_phases:
                row.phase = terminal
                row.started_at = None
        if success:
            for task_row in self._iter_task_delegation_rows():
                if (task_row.phase or "pending").strip().lower() in (
                    "pending",
                    "running",
                    "skipped",
                ):
                    task_row.phase = "success"
                    task_row.started_at = None
        self._refresh_task_activity_display()
        self._refresh_tools_display()

    def iter_open_tool_calls_for_interrupt(self) -> list[dict[str, Any]]:
        """Tool call dicts for interrupted AIMessage state (non-task rows only)."""
        out: list[dict[str, Any]] = []
        for row in self._rows:
            if row.phase in ("pending", "running"):
                out.append(
                    {
                        "id": row.tool_call_id,
                        "name": row.tool_name,
                        "args": dict(row.args),
                    }
                )
        return out

    def snapshot_tool_rows(self) -> list[dict[str, Any]]:
        """Serialize tool rows for ``MessageData`` (IG-402)."""
        return [
            {
                "id": r.tool_call_id,
                "name": r.tool_name,
                "args": dict(r.args),
                "phase": r.phase,
                "output": r.output,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at,
                "parent_tool_call_id": r.parent_tool_call_id,
                "is_task_row": r.is_task_row,
            }
            for r in self._rows
        ]

    def apply_tool_rows_snapshot(self, rows: list[dict[str, Any]]) -> None:
        """Restore tool rows from :meth:`snapshot_tool_rows` output."""
        self._rows = []
        self._row_index = {}
        for raw in rows or []:
            tcid = str(raw.get("id", "")).strip()
            if not tcid:
                continue
            name = str(raw.get("name", "tool") or "tool")
            args = raw.get("args")
            if not isinstance(args, dict):
                args = {}
            phase = str(raw.get("phase", "pending"))
            is_task = bool(raw.get("is_task_row")) or is_step_level_task_tool_id(tcid)
            parent = raw.get("parent_tool_call_id")
            parent_id = str(parent).strip() if parent else None
            row = _StepToolRow(
                tool_call_id=tcid,
                tool_name=name,
                args=dict(args),
                phase=phase,
                output=str(raw.get("output", "") or ""),
                duration_ms=int(raw.get("duration_ms", 0) or 0),
                started_at=raw.get("started_at"),
                parent_tool_call_id=parent_id,
                is_task_row=is_task,
            )
            self._rows.append(row)
            self._row_index[tcid] = row
        self._rebuild_tool_stats()
        self._refresh_header_title()
        self._refresh_tools_display()
        self._sync_running_status_line()

    def _sync_running_status_line(self) -> None:
        """Refresh status text when tool stats change without repainting tool rows.

        This method is called when tool calls arrive during a running step,
        so it updates the status line immediately (without visibility check)
        to show the tool count in real-time.
        """
        if self._status == "running":
            self._sync_running_status_text()
        elif self._status == "queued":
            self._refresh_queued_display()
        elif self._status == "pending":
            self._refresh_pending_display()

    def _sync_running_status_text(self) -> None:
        """Update running status line text immediately (no visibility check).

        Called when tool stats change during running state to show tool count
        in real-time, bypassing the animation visibility check that would
        prevent updates for newly-mounted or off-screen widgets.
        """
        if self._status != "running" or self._status_widget is None:
            return
        frames = get_glyphs().spinner_frames
        frame = frames[self._spinner_position]
        elapsed = ""
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
            elapsed = f" ({format_duration(float(elapsed_secs))})"
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = f"{get_glyphs().output_prefix} "
        stats_suffix = self._stats_title_suffix()
        token_suffix = self._token_budget_suffix()
        # IG-504: Show retry count in running status when retries are happening
        retry_suffix = ""
        if self._retry_attempt > 0 and self._max_retry_attempts > 0:
            retry_suffix = f" ({self._retry_attempt}/{self._max_retry_attempts} attempts)"
        head = f"{gutter}{frame} Running{retry_suffix}...{elapsed}"
        tail = f"{stats_suffix}{token_suffix}"
        clear_widget_text_selection(self._status_widget)
        parts: list[object] = [Content.styled(head, colors.warning)]
        if tail:
            parts.append(Content.styled(tail, colors.cognition))
        self._status_widget.display = True
        self._status_widget.update(Content.assemble(*parts))

    def _refresh_pending_display(self) -> None:
        """Show waiting state for planned steps that are not executing yet."""
        if self._status != "pending" or self._status_widget is None:
            return
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        line = f"{gutter}{g.circle_empty} Pending...{self._stats_title_suffix()}{self._token_budget_suffix()}"
        self._status_widget.remove_class("queued")
        self._status_widget.add_class("pending")
        self._status_widget.update(Content.styled(line, colors.cognition))
        self._status_widget.display = True
        self._refresh_task_activity_display()

    def _refresh_queued_display(self) -> None:
        """Show ready steps waiting for a concurrency slot (``max_parallel_steps``)."""
        if self._status != "queued" or self._status_widget is None:
            return
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        line = f"{gutter}{g.circle_empty} Queued...{self._stats_title_suffix()}{self._token_budget_suffix()}"
        self._status_widget.remove_class("pending")
        self._status_widget.add_class("queued")
        self._status_widget.update(Content.styled(line, colors.cognition))
        self._status_widget.display = True
        self._refresh_task_activity_display()

    def set_queued(self) -> None:
        """Mark a ready step as waiting for an execute batch slot."""
        if self._status in ("running", "success", "error"):
            return
        self._status = "queued"
        self._refresh_queued_display()

    def set_running(self) -> None:
        """Show animated running state (call after mount)."""
        if self._status == "running":
            return
        self._status = "running"
        self._step_card_user_expanded = False
        self._step_tool_list_user_expanded = False
        self._start_time = time()
        self._tools_body_collapsed = False
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.remove_class("queued")
            self._status_widget.display = True
        # Immediate status line update (bypasses visibility check) so tool count
        # appears in real-time when tools arrive before the animation timer fires.
        self._sync_running_status_text()
        self._refresh_task_activity_display()
        self._animation_timer = self.set_interval(
            _RUNNING_SPINNER_INTERVAL_SECONDS,
            self._update_running_animation,
        )

    def _stop_animation(self) -> None:
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def set_retry_status(self, attempt: int, max_attempts: int, error_type: str) -> None:
        """IG-504: Update retry status for running animation display.

        Args:
            attempt: Current attempt number (1-indexed).
            max_attempts: Maximum attempts allowed.
            error_type: "timeout" or "rate_limit".
        """
        self._retry_attempt = attempt
        self._max_retry_attempts = max_attempts
        self._retry_error_type = error_type
        # Trigger immediate refresh of running status (bypass visibility check)
        if self._status == "running":
            self._sync_running_status_text()

    def _update_running_animation(self) -> None:
        """Animation timer callback: advance spinner and update status line.

        The visibility check here is for efficiency - skipping expensive
        re-renders when the widget is off-screen. For immediate tool-stats
        updates (called when tool calls arrive), use `_sync_running_status_text`
        which bypasses this check.
        """
        if self._status != "running" or self._status_widget is None:
            return
        if not _is_widget_animation_visible(self):
            return
        # Advance spinner position for animation effect
        frames = get_glyphs().spinner_frames
        self._spinner_position = (self._spinner_position + 1) % len(frames)
        # Update status line with current stats
        self._sync_running_status_text()
        if self._has_active_task_branch_animation():
            self._refresh_task_activity_display()

    def set_complete(
        self,
        success: bool,
        duration_ms: int,
        tool_call_count: int,
        summary: str,
    ) -> None:
        """Finalize step with duration, tool count, and summary text."""
        self._stop_animation()
        self._status = "success" if success else "error"
        self._last_success = success
        self._last_duration_ms = duration_ms
        self._last_tool_call_count = tool_call_count
        self._last_summary = summary.strip()
        if self._status_widget is None or self._detail_widget is None:
            self._deferred_complete = (success, duration_ms, tool_call_count, summary)
            return

        self.mark_unfinished_tools_on_step_complete(success=success)
        self._tools_body_collapsed = True
        self._refresh_tools_display(force=True)

        dur_str = format_duration_ms(duration_ms)
        tool_part = self._status_tool_stats_suffix(tool_call_count)
        token_suffix = self._token_budget_suffix()

        prose = self._execute_assistant_buffer.strip()
        self._last_completed_execute_prose = prose
        self._execute_assistant_buffer = ""

        if success:
            self._update_step_footer_status_line(
                f"Completed ({dur_str})",
                success=True,
                suffix=f"{tool_part}{token_suffix}",
            )
            self._refresh_task_activity_display()
            if prose:
                self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                self._detail_widget.display = True
            else:
                self._detail_widget.display = False
            self._maybe_auto_collapse_step_card()
            return

        err_text = summary.strip() or "Step failed"
        self._update_step_footer_status_line(f"Failed · {dur_str}{token_suffix}", success=False)
        if prose:
            err_text = f"{err_text}\n\n{prose}"
        self._detail_widget.update(self._step_branched_error_detail(err_text))
        self._detail_widget.display = True
        self._maybe_auto_collapse_step_card()

    def set_clarification_details(
        self,
        *,
        questions: list[str],
        answers: list[str],
        source: str,
        confidence: float | None,
    ) -> None:
        """Render Q&A pairs for an ask_user step on the detail widget.

        Called after :meth:`set_complete` for steps whose ``step_completed``
        event payload includes a ``clarification`` block (RFC-622, RFC-623).
        Lays out one ``Q: ... / A: ...`` pair per question with a header line
        showing the answer source and (optional) veritas confidence.
        """
        if self._detail_widget is None:
            return
        if not questions and not answers:
            return
        header_bits = [f"source={source or 'unknown'}"]
        if confidence is not None:
            header_bits.append(f"confidence={confidence:.2f}")
        header = "Answered (" + ", ".join(header_bits) + ")"
        lines: list[str] = [header]
        pair_count = max(len(questions), len(answers))
        for i in range(pair_count):
            q = questions[i].strip() if i < len(questions) else ""
            a = answers[i].strip() if i < len(answers) else ""
            if q:
                lines.append(f"Q{i + 1}: {q}")
            if a:
                lines.append(f"A{i + 1}: {a}")
            else:
                lines.append(f"A{i + 1}: (no answer)")
        body = "\n".join(lines)
        self._detail_widget.update(self._step_branched_execute_body(body, muted=True))
        self._detail_widget.display = True

    def set_result_preview(self, text: str) -> None:
        """Show a 3-line preview of the goal_completion result in the detail area."""
        if not text.strip():
            return
        lines = text.strip().splitlines()
        preview_lines = lines[:3]
        preview = "\n".join(preview_lines)
        remaining = len(lines) - 3
        if remaining > 0:
            ellipsis = get_glyphs().ellipsis
            preview += f"\n{ellipsis} {remaining} more lines"
        if self._detail_widget is None:
            return
        g = get_glyphs()
        sub = f"{g.output_prefix} {g.circle_empty} "
        assembled: list[object] = []
        if self._last_success is not None:
            dur_str = format_duration_ms(self._last_duration_ms)
            tool_part = self._status_tool_stats_suffix(self._last_tool_call_count)
            token_suffix = self._token_budget_suffix()
            self._update_step_footer_status_line(
                f"Completed ({dur_str})",
                success=True,
                suffix=f"{tool_part}{token_suffix}",
            )
        first_pv = True
        for ln in preview.splitlines():
            if not first_pv:
                assembled.append("\n")
            first_pv = False
            assembled.append(Content.styled(f"{sub}{ln}", "dim"))
        self._detail_widget.update(Content.assemble(*assembled))
        self._detail_widget.display = True

    def set_awaiting_clarification(self, questions: list[str]) -> None:
        """Pause the running animation and show the pending questions.

        Called when a ``soothe.loop.clarification.requested`` event arrives
        while the loop graph is suspended on ``await_clarification``
        (RFC-622 / RFC-623). Stops the spinner, marks the card as awaiting an
        answer, and renders the questions in the detail area so the user
        knows what to type. ``set_clarification_details`` will replace the
        body with the Q&A pairs once ``step_completed`` arrives.
        """
        clean = [q.strip() for q in questions if q and q.strip()]
        if not clean:
            return
        self._stop_animation()
        self._status = "pending"
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001  # Unmounted widget (tests / no Textual app)
            colors = theme.DARK_COLORS
        if self._status_widget is not None:
            g = get_glyphs()
            gutter = f"{g.output_prefix} "
            line = f"{gutter}{g.circle_empty} Awaiting your answer..."
            self._status_widget.remove_class("queued")
            self._status_widget.add_class("pending")
            self._status_widget.update(Content.styled(line, colors.warning))
            self._status_widget.display = True
        if self._detail_widget is not None:
            lines = [f"Q{i + 1}: {q}" for i, q in enumerate(clean)]
            body = "\n".join(lines)
            self._detail_widget.update(self._step_branched_execute_body(body, muted=False))
            self._detail_widget.display = True

    def set_interrupted(self, message: str) -> None:
        """Mark step as aborted (stream error / cancel) while still running."""
        self._stop_animation()
        self._status = "error"
        self._execute_assistant_buffer = ""
        self._last_completed_execute_prose = ""
        self._interrupt_message = message
        for row in self._rows:
            if row.phase in ("pending", "running"):
                row.phase = "skipped"
                row.started_at = None
        self._refresh_tools_display()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001  # Unmounted widget (tests / no Textual app)
            colors = theme.DARK_COLORS
        if self._status_widget:
            self._status_widget.remove_class("pending")
            self._status_widget.add_class("error")
            self._status_widget.update(Content.styled(message, colors.error))
            self._status_widget.display = True
        if self._detail_widget:
            self._detail_widget.display = False
