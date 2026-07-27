"""Cognition step message widget."""

from __future__ import annotations

import json
import logging
from time import monotonic, time
from typing import TYPE_CHECKING, Any, NamedTuple

from soothe_sdk.ux.task_namespace import (
    is_step_level_task_tool_id,
    normalize_step_task_tool_call_id,
    parse_unified_tool_call_id,
)
from textual.containers import Vertical
from textual.content import Content
from textual.events import Click
from textual.widgets import Static

from soothe_cli.runtime.presentation.duration_format import format_duration_ms
from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import STEP_CARD_SHOW_TOOL_ROW_DETAILS
from soothe_cli.tui.tool_display import format_step_tool_activity_line
from soothe_cli.tui.widgets.clipboard import (
    clear_widget_text_selection,
    screen_has_text_selection,
)
from soothe_cli.tui.widgets.messages._helpers import (
    _RUNNING_SPINNER_INTERVAL_SECONDS,
    _STEP_TOOL_PREVIEW_ROWS,
    _assemble_card_header,
    _is_widget_animation_visible,
    _should_refresh_now,
    _strip_success_exit_line,
    request_deferred_tools_refresh,
)
from soothe_cli.tui.widgets.messages.cognition_step_activity import (
    StepActivityTree,
    StepCardStatusLine,
    StepRowClassifier,
    StepRowIndex,
    branched_prose_body,
    finalize_tool_rows_on_step_end,
    has_task_activity_body,
    latest_preview_rows,
    normalized_task_note_key,
    phase_icon,
    stats_title_suffix,
    task_delegation_dedupe_key,
    task_tool_row_tone,
)
from soothe_cli.tui.widgets.messages.cognition_step_activity import (
    StepToolRow as _StepToolRow,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

logger = logging.getLogger(__name__)


class _DeferredStepComplete(NamedTuple):
    success: bool
    duration_ms: int
    tool_call_count: int
    summary: str


class CognitionStepMessage(Vertical):
    """Agent-loop act step card (RFC-628).

    Header is the step description only. Task delegations render in a branch panel
    (``Name(desc)`` plus the latest tool activity lines and nested stats). Footer and
    branch Running lines show tool totals via ``stats_title_suffix`` on ``StepRowIndex``
    (e.g. `` · 12 tools, 1 task`` on the footer; `` · 6 tools`` under a delegation branch).
    The status line is always the last body line (running, pending, completed, failed).
    Optional full tool lists use ``STEP_CARD_SHOW_TOOL_ROW_DETAILS``. Click toggles
    manual whole-card collapse; cards do not auto-collapse.

    Pure rendering and classification live in ``cognition_step_activity.py``.
    Card headers use a stateful card-prefix glyph (see ``_assemble_card_header``); body
    lines use the goal-tree gutter (``⎿``) plus hollow/filled circles when shown.
    Prose / notes keep ``⎿ ○`` continuation lines.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionStepMessage {
        height: auto;
        padding: 0 2;
        margin: 0 0 1 0;
        background: transparent;
    }

    CognitionStepMessage .step-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionStepMessage .step-tools {
        height: auto;
        color: $text-muted;
    }

    CognitionStepMessage .step-subagent-notes {
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-detail {
        margin-top: 0;
        color: $text-muted;
        height: auto;
    }

    CognitionStepMessage .step-status {
        height: auto;
        color: $text-muted;
    }

    CognitionStepMessage.-collapsed .step-tools,
    CognitionStepMessage.-collapsed .step-status,
    CognitionStepMessage.-collapsed .step-subagent-notes,
    CognitionStepMessage.-collapsed .step-detail {
        display: none;
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
        self._status = "pending"  # pending | running | success | error
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
        self._activity_widget: Static | None = None
        self._deferred_complete: _DeferredStepComplete | None = None
        self._deferred_running: bool = False
        self._deferred_surface_sync: bool = False
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
        self._execute_assistant_buffer: str = ""
        self._last_completed_execute_prose: str = ""
        """Execute-step prose frozen when ``set_complete`` runs (TUI dedupe vs goal_completion)."""
        self._card_collapsed: bool = False
        """Whether the entire card body is collapsed (header remains visible)."""
        self._step_tool_list_user_expanded: bool = False
        """If True, skip auto-folding the tool-row preview (user expanded the list)."""
        self._has_clarification_details: bool = False
        """Whether detail panel currently holds clarification Q/A content."""

    def _build_row_index(self) -> StepRowIndex:
        """Classify tool rows once for stats, previews, and activity rendering."""
        return StepRowClassifier.build(self._step_id, self._rows)

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
        """Accumulate LLM token usage for this step or SubAgent card."""
        if not input_tokens and not output_tokens:
            return
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        if self._status in ("running", "pending"):
            self._sync_step_card_surface()

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
            self._description,
            status=self._status,
            spinner_position=self._spinner_position,
            animate_running=self._status == "running",
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

    def _flush_deferred_state_on_mount(self) -> None:
        """Apply deferred lifecycle state in a stable order after mount."""
        if self._deferred_interrupted is not None:
            msg = self._deferred_interrupted
            self._deferred_interrupted = None
            self.set_interrupted(msg)
            return
        if self._deferred_complete is not None:
            deferred = self._deferred_complete
            self._deferred_complete = None
            self.set_complete(
                deferred.success,
                deferred.duration_ms,
                deferred.tool_call_count,
                deferred.summary,
            )
            return
        if self._deferred_running:
            self._deferred_running = False
            self.set_running()
            return
        if self._deferred_surface_sync:
            self._deferred_surface_sync = False
            self._sync_step_card_surface()
            return
        if self._status == "running":
            self._ensure_running_ui()
        elif self._status == "pending":
            self._sync_step_card_surface()

    def on_mount(self) -> None:
        self._header_widget = self.query_one("#step-cognition-header", Static)
        self._status_widget = self.query_one("#step-cognition-status", Static)
        self._tools_widget = self.query_one("#step-cognition-tools", Static)
        self._detail_widget = self.query_one("#step-cognition-detail", Static)
        self._activity_widget = self.query_one("#step-cognition-subagent-notes", Static)
        self._activity_widget.display = False
        self._status_widget.display = False
        self._tools_widget.display = False
        self._detail_widget.display = False
        self._refresh_header_title()
        if self._execute_assistant_buffer.strip() and self._status == "running":
            self._refresh_execute_assistant_running_display()
        self._flush_deferred_state_on_mount()

    def on_click(self, event: Click) -> None:  # noqa: ARG002
        """Toggle tool-row folding or card collapse."""
        event.stop()
        if screen_has_text_selection(self.screen):
            return
        # If the whole card body is collapsed, always expand it first so one
        # click reliably reveals details (e.g. clarification Q/A content).
        if self._card_collapsed:
            self.toggle_collapse()
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
        self._card_collapsed = not self._card_collapsed
        self._refresh_collapse_state()

    def _refresh_collapse_state(self) -> None:
        """Update CSS classes and completion footer when manual collapse toggles."""
        if self._card_collapsed:
            self.add_class("-collapsed")
        else:
            self.remove_class("-collapsed")
        if self._status in ("success", "error") and self._detail_widget:
            dur_str = format_duration_ms(self._last_duration_ms)
            tool_part = self._status_tool_stats_suffix(self._last_tool_call_count)
            if self._last_success:
                self._update_step_footer_status_line(
                    f"Completed ({dur_str})",
                    success=True,
                    suffix=tool_part,
                )
                prose = (self._last_completed_execute_prose or "").strip()
                if prose:
                    self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                    self._detail_widget.display = True
                elif self._has_clarification_details:
                    # Preserve non-prose detail content (e.g. clarification Q/A)
                    # when toggling collapsed state on completed cards.
                    self._detail_widget.display = True
                else:
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

    def _refresh_execute_assistant_running_display(self) -> None:
        body = self._execute_assistant_buffer.strip()
        if not body or self._detail_widget is None:
            return
        self._detail_widget.update(self._step_branched_execute_body(body, muted=True))
        self._detail_widget.display = True

    def _has_task_activity_body(self) -> bool:
        """True when the step card should show the task-activity tree panel."""
        index = self._build_row_index()
        return has_task_activity_body(index, self._subagent_notes, self._subagent_notes_by_task)

    @staticmethod
    def _latest_preview_rows(
        rows: list[_StepToolRow],
        limit: int | None = None,
    ) -> list[_StepToolRow]:
        """Return the most recently appended rows, capped at ``limit``."""
        if limit is None:
            return latest_preview_rows(rows)
        return latest_preview_rows(rows, limit)

    def _main_agent_tool_rows_for_preview(self) -> list[_StepToolRow]:
        """Direct main-agent tool rows (excludes task delegations and subgraph tools)."""
        return self._build_row_index().main_tools

    def _task_delegation_dedupe_key(self, row: _StepToolRow) -> str:
        """Stable key for one main-graph task delegation (aliases share one branch)."""
        return task_delegation_dedupe_key(row, self._step_id)

    def _iter_task_delegation_rows(self) -> list[_StepToolRow]:
        """Task delegation rows on this step (unified ``{step}:s:task:…`` ids)."""
        return self._build_row_index().task_delegations

    def _phase_icon(self, phase: str, g: Any, *, animate_running: bool = False) -> str:
        """Lifecycle glyph for a task branch or tool row."""
        return phase_icon(
            phase,
            g,
            spinner_position=self._spinner_position,
            animate_running=animate_running,
        )

    def _normalized_task_note_key(self, task_tool_call_id: str) -> str:
        return normalized_task_note_key(self._step_id, task_tool_call_id)

    def _step_task_activity_content(self) -> Content:
        """Task delegations, latest tool activity lines, and notes under the step title."""
        g = get_glyphs()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        index = self._build_row_index()
        return StepActivityTree.render(
            step_id=self._step_id,
            step_status=self._status,
            index=index,
            subagent_notes=self._subagent_notes,
            subagent_notes_by_task=self._subagent_notes_by_task,
            spinner_position=self._spinner_position,
            colors=colors,
            g=g,
        )

    def _sync_step_card_surface(self) -> None:
        """Repaint activity panel, footer status, optional tools list, and timer."""
        mounted = getattr(self, "is_mounted", False)
        has_cached_widgets = self._status_widget is not None or self._activity_widget is not None
        if not mounted and not has_cached_widgets:
            self._deferred_surface_sync = True
            return
        self._deferred_surface_sync = False
        index = self._build_row_index()
        activity_widget = self._activity_widget
        if activity_widget is None:
            try:
                activity_widget = self.query_one("#step-cognition-subagent-notes", Static)
                self._activity_widget = activity_widget
            except Exception:  # noqa: BLE001
                activity_widget = None
        if activity_widget is not None:
            show = has_task_activity_body(index, self._subagent_notes, self._subagent_notes_by_task)
            if show:
                activity_widget.update(self._step_task_activity_content())
                activity_widget.display = True
            else:
                activity_widget.display = False

        if self._status == "running":
            self._sync_running_status_text(index)
        elif self._status == "pending":
            self._refresh_pending_display(index)

        if STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            self._refresh_tools_display()

        self._maybe_start_running_timer()

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
        self._sync_step_card_surface()

    def _stats_title_suffix(self) -> str:
        """Step status suffix: total tool count plus task delegation count."""
        return stats_title_suffix(self._build_row_index())

    def _status_tool_stats_suffix(self, fallback_count: int = 0) -> str:
        """Tracked scope-local totals for status lines.

        Step cards use ``total_tool_count`` (main + subgraph). Intake-only orphan
        SubAgent cards use the same index over their filtered subgraph rows.
        Server ``tool_call_count`` is only a fallback when no local rows exist.
        """
        index = self._build_row_index()
        tool_count = index.total_tool_count
        # Server totals can inflate when only task markers exist locally.
        if tool_count == 0 and fallback_count > 0 and index.task_delegation_count == 0:
            tool_count = fallback_count
        parts: list[str] = []
        if tool_count:
            from soothe_cli.tui.widgets.messages.cognition_step_activity import (
                format_tool_count_label,
            )

            parts.append(format_tool_count_label(tool_count, singular="tool", plural="tools"))
        if index.task_delegation_count:
            from soothe_cli.tui.widgets.messages.cognition_step_activity import (
                format_tool_count_label,
            )

            parts.append(
                format_tool_count_label(
                    index.task_delegation_count, singular="task", plural="tasks"
                )
            )
        if parts:
            return f" · {', '.join(parts)}"
        if fallback_count > 0:
            return f" · {fallback_count} tools"
        return ""

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
            success: Whether this is a successful completion (dim, like tool
                activity rows) or a failure (red).
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
        self._status_widget.update(
            StepCardStatusLine.footer_completed(
                gutter=gutter,
                icon=icon,
                head=head,
                suffix=suffix,
                success=success,
                colors=colors,
            )
        )
        self._status_widget.display = True

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
            error=str(row.output or "") if phase == "error" else "",
        )
        tone = task_tool_row_tone(row, colors)
        return Content.styled(f"{gutter}{icon} {body}", tone)

    def _step_branched_execute_body(self, body: str, *, muted: bool = True) -> Content:
        """Streamed execute-phase prose: tree gutter per line."""
        g = get_glyphs()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        style = colors.muted if muted else colors.success
        return branched_prose_body(
            body,
            gutter=f"{g.output_prefix} ",
            circle_empty=g.circle_empty,
            style=style,
        )

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

    def _build_tools_panel_row_order(self) -> list[_StepToolRow]:
        """Flat row order for the optional full tools panel (RFC-628)."""
        index = self._build_row_index()
        return list(index.task_delegations) + list(index.main_tools)

    def request_tools_display_refresh(self, *, immediate: bool = False) -> None:
        """Queue or run a card surface repaint (batched across cards during streaming)."""
        if immediate:
            self._tools_refresh_pending = False
            self._sync_step_card_surface()
            return
        self._tools_refresh_pending = True
        request_deferred_tools_refresh(self)

    def _flush_deferred_tools_refresh(self) -> None:
        if not self._tools_refresh_pending:
            return
        self._tools_refresh_pending = False
        self._sync_step_card_surface()

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
        """Repaint the optional full nested tool list panel."""
        if self._tools_widget is None:
            return
        if not STEP_CARD_SHOW_TOOL_ROW_DETAILS:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            return
        if not force and not _should_refresh_now(self._last_tools_refresh):
            return
        self._last_tools_refresh = monotonic()
        if not self._rows:
            self._tools_widget.display = False
            self._row_cache_key_by_id.clear()
            self._row_content_by_id.clear()
            self._tools_panel_cache_key = None
            return
        self._maybe_auto_fold_step_tool_list()
        self._tools_widget.display = True
        ordered_rows = self._build_tools_panel_row_order()
        show_all = len(ordered_rows) <= _STEP_TOOL_PREVIEW_ROWS or not self._tools_body_collapsed
        visible = ordered_rows if show_all else ordered_rows[:_STEP_TOOL_PREVIEW_ROWS]
        panel_key: tuple[Any, ...] = (
            tuple(self._row_content_cache_key(r) for r in visible),
            show_all,
            self._tools_body_collapsed,
        )
        if not force and panel_key == self._tools_panel_cache_key:
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

    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        raw_args: str = "",
        is_task_row: bool = False,
    ) -> None:
        """Register a new tool row (pending).

        Args:
            tool_call_id: Unique tool call identifier.
            tool_name: Tool name for display.
            args: Parsed tool arguments.
            raw_args: Raw JSON args string from streaming (stored on the row for
                later merge when args arrive incrementally).
            is_task_row: Mark as task delegation row (flat marker on step card).
        """
        tcid = str(tool_call_id).strip()
        if not tcid:
            return
        if not is_task_row:
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
        # IG-517: Deduplicate task rows by semantic identity before creating.
        # Multiple streaming chunks may arrive with different raw tool_call_ids
        # for the same delegation (same subagent_type + description). Check for
        # existing task row with matching semantics, not just tool_call_id.
        if is_task_row and tool_name == "task":
            from soothe_cli.tui.tool_display import compact_arg_text

            candidate_subagent = str(args.get("subagent_type") or "").strip()
            candidate_desc = str(args.get("description") or args.get("prompt") or "").strip()
            candidate_desc_compact = compact_arg_text(candidate_desc)
            for existing_row in self._rows:
                if not getattr(existing_row, "is_task_row", False):
                    continue
                existing_args = existing_row.args or {}
                existing_subagent = str(existing_args.get("subagent_type") or "").strip()
                existing_desc = str(
                    existing_args.get("description") or existing_args.get("prompt") or ""
                ).strip()
                existing_desc_compact = compact_arg_text(existing_desc)
                # Match by subagent_type + description semantics
                if candidate_subagent == existing_subagent:
                    # If both have descriptions, compare compacted form (allows minor diffs)
                    if candidate_desc_compact and existing_desc_compact:
                        if candidate_desc_compact == existing_desc_compact:
                            self.update_tool_args(existing_row.tool_call_id, args)
                            return
                    # If only subagent_type matches and one has no description,
                    # treat as same delegation (streaming may fill description later)
                    elif not candidate_desc_compact or not existing_desc_compact:
                        self.update_tool_args(existing_row.tool_call_id, args)
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
                from soothe_sdk.display.message_processing import extract_tool_args_dict

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
            is_task_row=is_task_row,
        )
        if not is_task_row:
            _, type_code, _, _ = parse_unified_tool_call_id(tcid)
            if type_code == "t":
                row.phase = "running"
                row.started_at = time()
        self._rows.append(row)
        self._row_index[tcid] = row
        self._refresh_header_title()
        self._sync_step_card_surface()

    def promote_to_running_if_pending(self) -> None:
        """Transition ``pending`` → ``running`` (RFC-628 authorized promotion only)."""
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

    def row_duration_ms_since_started(self, tool_call_id: str) -> int:
        """Elapsed ms since this row entered running state (for result lines)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.started_at is None:
            return 0
        return int((time() - row.started_at) * 1000)

    def update_tool_args(self, tool_call_id: str, args: dict[str, Any]) -> None:
        """Refresh kwargs when streaming fills in arguments."""
        from soothe_sdk.display.message_processing import extract_tool_args_dict

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
        self._sync_step_card_surface()

    def set_tool_running(self, tool_call_id: str) -> None:
        """Mark a tool row as executing (after approval)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None or row.phase not in ("pending", "running"):
            return
        row.phase = "running"
        row.started_at = time()
        self._sync_step_card_surface()

    def set_tool_success(self, tool_call_id: str, result: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as success."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "success"
        row.output = _strip_success_exit_line(result)
        row.duration_ms = duration_ms
        row.started_at = None
        self._sync_step_card_surface()

    def set_tool_error(self, tool_call_id: str, error: str, *, duration_ms: int = 0) -> None:
        """Finalize a tool row as error."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "error"
        row.output = error
        row.duration_ms = duration_ms
        row.started_at = None
        self._sync_step_card_surface()

    def set_tool_rejected(self, tool_call_id: str) -> None:
        """Mark a tool row as rejected."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "rejected"
        row.started_at = None
        self._sync_step_card_surface()

    def set_tool_skipped(self, tool_call_id: str) -> None:
        """Mark a tool row skipped (batch reject / incomplete)."""
        row = self._row_index.get(str(tool_call_id))
        if row is None:
            return
        row.phase = "skipped"
        row.started_at = None
        self._sync_step_card_surface()

    def mark_unfinished_tools_skipped(self) -> None:
        """Mark pending/running rows skipped when the step ends without results."""
        self.mark_unfinished_tools_on_step_complete(success=False)

    def mark_unfinished_tools_on_step_complete(self, *, success: bool) -> None:
        """Finalize open tool rows when the step card completes.

        On successful steps, pending/running/skipped tools are marked ``success``
        so branches show Done instead of Skipped/Pending when the task finished
        without per-tool ToolMessage events.
        """
        finalize_tool_rows_on_step_end(
            self._rows,
            self._iter_task_delegation_rows(),
            success=success,
        )
        self._sync_step_card_surface()

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
        self._refresh_header_title()
        self._sync_step_card_surface()

    def _sync_running_status_text(self, index: StepRowIndex | None = None) -> None:
        """Update running status line text immediately (no visibility check)."""
        if self._status != "running" or self._status_widget is None:
            return
        if index is None:
            index = self._build_row_index()
        g = get_glyphs()
        frames = g.spinner_frames
        frame = frames[self._spinner_position]
        elapsed_secs: int | None = None
        if self._start_time is not None:
            elapsed_secs = int(time() - self._start_time)
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = f"{g.output_prefix} "
        stats_suffix = stats_title_suffix(index)
        token_suffix = self._token_budget_suffix()
        retry_suffix = ""
        if self._retry_attempt > 0 and self._max_retry_attempts > 0:
            retry_suffix = f" ({self._retry_attempt}/{self._max_retry_attempts} attempts)"
        clear_widget_text_selection(self._status_widget)
        self._status_widget.display = True
        self._status_widget.update(
            StepCardStatusLine.footer_running(
                gutter=gutter,
                spinner_frame=frame,
                elapsed_secs=elapsed_secs,
                stats_suffix=stats_suffix,
                token_suffix=token_suffix,
                retry_suffix=retry_suffix,
                colors=colors,
            )
        )

    def _refresh_pending_display(self, index: StepRowIndex | None = None) -> None:
        """Show waiting state for planned steps that are not executing yet."""
        if self._status != "pending" or self._status_widget is None:
            return
        if index is None:
            index = self._build_row_index()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        g = get_glyphs()
        gutter = f"{g.output_prefix} "
        self._status_widget.update(
            StepCardStatusLine.footer_pending(
                gutter=gutter,
                circle_empty=g.circle_empty,
                stats_suffix=stats_title_suffix(index),
                token_suffix=self._token_budget_suffix(),
                colors=colors,
            )
        )
        self._status_widget.display = True

    def _maybe_start_running_timer(self) -> None:
        """Start the spinner timer when the step is running and mounted."""
        if self._status != "running":
            return
        if self._start_time is None:
            self._start_time = time()
        if self._status_widget:
            self._status_widget.display = True
        if self._animation_timer is None and getattr(self, "is_mounted", False):
            self._animation_timer = self.set_interval(
                _RUNNING_SPINNER_INTERVAL_SECONDS,
                self._update_running_animation,
            )

    def _ensure_running_ui(self) -> None:
        """Paint running footer/branch status and start the spinner timer if needed."""
        if self._status != "running":
            return
        self._sync_step_card_surface()

    def set_running(self) -> None:
        """Show animated running state (call after mount)."""
        if self._status == "running":
            self._ensure_running_ui()
            return
        self._status = "running"
        self._has_clarification_details = False
        self._step_tool_list_user_expanded = False
        self._start_time = time()
        self._tools_body_collapsed = False
        self._refresh_header_title()
        self._ensure_running_ui()

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
            self._sync_step_card_surface()

    def _update_running_animation(self) -> None:
        """Animation timer callback: advance spinner and repaint the card surface."""
        if self._status != "running" or self._status_widget is None:
            return
        if not _is_widget_animation_visible(self):
            return
        frames = get_glyphs().spinner_frames
        self._spinner_position = (self._spinner_position + 1) % len(frames)
        self._refresh_header_title()
        self._sync_step_card_surface()

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
        self._refresh_header_title()
        self._last_success = success
        self._last_duration_ms = duration_ms
        self._last_tool_call_count = tool_call_count
        self._last_summary = summary.strip()
        if self._status_widget is None or self._detail_widget is None:
            self._deferred_complete = _DeferredStepComplete(
                success, duration_ms, tool_call_count, summary
            )
            return

        self.mark_unfinished_tools_on_step_complete(success=success)
        self._tools_body_collapsed = True
        if STEP_CARD_SHOW_TOOL_ROW_DETAILS:
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
            self._sync_step_card_surface()
            if prose:
                self._detail_widget.update(self._step_branched_execute_body(prose, muted=True))
                self._detail_widget.display = True
            else:
                self._detail_widget.display = False
            return

        err_text = summary.strip() or "Step failed"
        self._update_step_footer_status_line(f"Failed · {dur_str}{token_suffix}", success=False)
        if prose:
            err_text = f"{err_text}\n\n{prose}"
        self._detail_widget.update(self._step_branched_error_detail(err_text))
        self._detail_widget.display = True
        self._sync_step_card_surface()

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
        self._has_clarification_details = True
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
        """Show a short preview of the goal_completion result in the detail area."""
        if not text.strip():
            return
        lines = text.strip().splitlines()
        preview_lines = lines[:8]
        preview = "\n".join(preview_lines)
        remaining = len(lines) - 8
        if remaining > 0:
            ellipsis = get_glyphs().ellipsis
            preview += f"\n{ellipsis} {remaining} more lines — full report below"
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
        self._refresh_header_title()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001  # Unmounted widget (tests / no Textual app)
            colors = theme.DARK_COLORS
        if self._status_widget is not None:
            g = get_glyphs()
            gutter = f"{g.output_prefix} "
            line = f"{gutter}{g.circle_empty} Awaiting your answer..."
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
        self._refresh_header_title()
        self._execute_assistant_buffer = ""
        self._last_completed_execute_prose = ""
        self._interrupt_message = message
        for row in self._rows:
            if row.phase in ("pending", "running"):
                row.phase = "skipped"
                row.started_at = None
        self._sync_step_card_surface()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001  # Unmounted widget (tests / no Textual app)
            colors = theme.DARK_COLORS
        if self._status_widget:
            if message.strip():
                self._status_widget.update(Content.styled(message, colors.error))
                self._status_widget.display = True
            else:
                self._status_widget.display = False
        if self._detail_widget:
            self._detail_widget.display = False

    def _sync_task_row_status_from_subagent(self, task_key: str, success: bool) -> None:
        """Update task row icon when a delegated task completes.

        Args:
            task_key: Dedupe key or raw task tool_call_id for the delegation row.
            success: True for success (✓ icon), False for error (✗ icon).
        """
        if not task_key:
            return
        # Accept either raw or normalized ids from wire lifecycle events.
        raw = str(task_key).strip()
        candidates = {raw, normalize_step_task_tool_call_id(self._step_id, raw)}
        for row in self._rows:
            if not getattr(row, "is_task_row", False):
                continue
            row_key = task_delegation_dedupe_key(row, self._step_id)
            if row_key in candidates or str(row.tool_call_id).strip() in candidates:
                row.phase = "success" if success else "error"
                row.started_at = None
                self._sync_step_card_surface()
                return
