"""Cognition goal tree message widget."""

from __future__ import annotations

import logging
import re
from time import time
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from soothe_cli.runtime.presentation.duration_format import (
    format_duration,
    format_duration_ms,
    format_running_elapsed,
)
from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

_MAX_GOAL_HEADER = 100
_MAX_GOAL_STEP_DESC = 80
_MAX_STEP_SUMMARY_TAIL = 80
_MAX_DEPENDENCY_IDS = 3

_DONE_WITH_TOOLS_RE = re.compile(r"^Done(?:\s*\[\d+\s+tools?\])?$", re.IGNORECASE)


def _dependency_suffix(deps: tuple[str, ...]) -> str:
    """Return a compact dependency hint for plan quick-view rows."""
    if not deps:
        return ""
    shown = deps[:_MAX_DEPENDENCY_IDS]
    text = ", ".join(shown)
    if len(deps) > _MAX_DEPENDENCY_IDS:
        text += ", …"
    return f" (→ {text})"


def _plan_quick_view_step_summary(
    success: bool,
    summary: str,
    *,
    tool_call_count: int = 0,
) -> str:
    """Return a Ctrl+T-safe step summary tail.

    Hides redundant ``Done [N tools]`` text (stats already show tool count) and
    legacy success payloads that still carry error-shaped summary strings.
    """
    tail = (summary or "").strip()
    if not tail or tail in ("Done", "Failed"):
        return ""
    if success and tool_call_count > 0 and _DONE_WITH_TOOLS_RE.match(tail):
        return ""
    if success:
        try:
            from soothe_sdk.display.tool_result import is_error_tool_result_text

            if is_error_tool_result_text(tail):
                return ""
        except Exception:  # noqa: BLE001
            logger.debug("plan quick view summary filter unavailable", exc_info=True)
    return tail


def _normalize_step_dependencies(raw_deps: Any) -> tuple[str, ...]:
    if not isinstance(raw_deps, list):
        return ()
    return tuple(str(dep).strip() for dep in raw_deps if str(dep).strip())


class _StepLineState:
    """Mutable row state for the goal → steps aggregate."""

    __slots__ = (
        "step_id",
        "description",
        "phase",
        "success",
        "duration_ms",
        "tool_call_count",
        "summary",
        "dependencies",
        "started_at",
    )

    def __init__(
        self,
        step_id: str,
        description: str,
        *,
        phase: str = "running",
        success: bool = True,
        duration_ms: int = 0,
        tool_call_count: int = 0,
        summary: str = "",
        dependencies: tuple[str, ...] = (),
        started_at: float | None = None,
    ) -> None:
        self.step_id = step_id
        self.description = description
        self.phase = phase
        self.success = success
        self.duration_ms = duration_ms
        self.tool_call_count = tool_call_count
        self.summary = summary
        self.dependencies = dependencies
        self.started_at = started_at


class CognitionGoalTreeMessage(Vertical):
    """Two-level Goal → steps tree; one aggregate block updates in place.

    Title line matches ``CognitionStepMessage`` / ``CognitionReasonMessage``:
    stateful card-prefix glyph plus goal text, with optional ``· iter<=N`` when
    ``max_iterations`` is set.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionGoalTreeMessage {
        height: auto;
        padding: 0 2;
        margin: 0 0 1 0;
        background: transparent;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-steps {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionGoalTreeMessage .cognition-goal-tree-footer {
        height: auto;
        margin: 0;
        color: $foreground;
    }
    """

    def __init__(
        self,
        *,
        goal: str,
        max_iterations: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize an empty goal tree (steps render as events arrive).

        Args:
            goal: Primary goal text (clipped for header).
            max_iterations: Shown in header when greater than 1.
            **kwargs: Passed to ``Vertical``.
        """
        super().__init__(**kwargs)
        self._goal_text = goal.strip()
        self._max_iterations = int(max_iterations)
        self._step_order: list[str] = []
        self._steps: dict[str, _StepLineState] = {}
        self._footer_plain: str = ""
        self._footer_visible: bool = False
        self._footer_tone: str = "muted"  # success | error | muted (step/tool completion parity)
        self._execution_mode: str = ""
        self._spinner_position: int = 0
        self._loop_started_at: float | None = None
        self._steps_static: Static | None = None

    @staticmethod
    def _clip(text: str, max_len: int) -> str:
        t = (text or "").strip().replace("\n", " ")
        if max_len <= 0:
            return "…"
        if len(t) <= max_len:
            return t
        if max_len == 1:
            return "…"
        return t[: max_len - 1].rstrip() + "…"

    def _loop_executing(self) -> bool:
        """True from loop start until a terminal footer (done / interrupted)."""
        return self._loop_started_at is not None and not self._footer_visible

    def _goal_tree_status(self) -> str:
        """Aggregate lifecycle status for the goal header dot."""
        if self._footer_visible:
            if self._footer_tone == "error":
                return "error"
            if self._footer_tone == "success":
                return "success"
        # Keep the goal "running" for the whole StrangeLoop — including planning
        # gaps between steps — so the plan panel / header match the thinking row.
        if self._loop_executing():
            return "running"
        phases = [st.phase for st in self._steps.values()]
        if any(p == "error" for p in phases):
            return "error"
        if phases and all(p == "done" for p in phases):
            return "success"
        if any(p == "queued" for p in phases):
            return "queued"
        return "pending"

    def _goal_header_content(self) -> Content:
        g = self._clip(self._goal_text, _MAX_GOAL_HEADER)
        body = g
        if self._max_iterations > 1:
            body = f"{body} · iter<={self._max_iterations}"
        mode = self._execution_mode.strip().lower()
        if mode:
            body = f"{body} · {mode}"
        status = self._goal_tree_status()
        return _assemble_card_header(
            self,
            body,
            status=status,
            glyph_override="🎯",
            spinner_position=self._spinner_position,
            animate_running=self._loop_executing(),
        )

    def _goal_footer_styled_content(self) -> Content:
        """Footer content for loop finished / interrupted (parity with step/tool status lines).

        The ``done`` (success) footer shares the title line's de-emphasized
        ``SECONDARY_TEXT_STYLE`` so the completion status blends with the
        "Orchestrate ..." header instead of using the cognition accent.
        """
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = self._indent_prefix()
        plain = self._footer_plain
        if self._footer_tone == "success":
            mark = get_glyphs().checkmark
            return Content.styled(f"{gutter}{mark} {plain}", theme.SECONDARY_TEXT_STYLE)
        if self._footer_tone == "error":
            mark = get_glyphs().error
            return Content.styled(f"{gutter}{mark} {plain}", colors.error)
        return Content.styled(f"{gutter}{plain}", theme.SECONDARY_TEXT_STYLE)

    def loop_elapsed_label(self) -> str | None:
        """Wall-clock elapsed while the goal loop is open, for the plan panel title."""
        if not self._loop_executing():
            return None
        started = self._loop_started_at or time()
        return format_running_elapsed(time() - started)

    def mark_loop_started(self, started_at: float | None = None) -> None:
        """Anchor plan-level elapsed time (matches thinking-row turn start)."""
        if self._loop_started_at is None:
            self._loop_started_at = started_at if started_at is not None else time()

    def _indent_prefix(self) -> str:
        g = get_glyphs()
        return f"{g.output_prefix} "

    def _step_icon(self, st: _StepLineState) -> str:
        g = get_glyphs()
        if st.phase == "pending" or st.phase == "queued":
            return g.circle_empty
        if st.phase == "running":
            frames = g.spinner_frames
            return frames[self._spinner_position % len(frames)]
        return g.checkmark if st.success else g.error

    def _step_stats_suffix(self, st: _StepLineState) -> str:
        """Duration and tool-count suffix for running or completed rows."""
        if st.phase == "running":
            parts: list[str] = []
            if st.started_at is not None:
                # Middot-separated live timer (matches step-card title elapsed meta).
                parts.append(format_running_elapsed(time() - st.started_at))
            if st.tool_call_count > 0:
                parts.append(f"{st.tool_call_count} tools")
            if not parts:
                return ""
            return " · " + " · ".join(parts)
        if st.phase not in ("done", "error"):
            return ""
        dur_s = max(0.001, st.duration_ms / 1000.0)
        parts = [format_duration(dur_s)]
        if st.tool_call_count > 0:
            parts.append(f"{st.tool_call_count} tools")
        return " · " + " · ".join(parts)

    def _step_summary_suffix(self, st: _StepLineState) -> str:
        if st.phase not in ("done", "error"):
            return ""
        tail = _plan_quick_view_step_summary(
            st.success,
            st.summary,
            tool_call_count=st.tool_call_count,
        )
        if not tail:
            return ""
        return f" — {self._clip(tail, _MAX_STEP_SUMMARY_TAIL)}"

    def _fit_step_line(
        self,
        st: _StepLineState,
        *,
        icon: str,
        max_line_width: int | None,
    ) -> str:
        """Build a single-line step row, clipping description to fit ``max_line_width``."""
        step_prefix = f"{st.step_id}: " if st.step_id else ""
        dep_suffix = _dependency_suffix(st.dependencies)
        queued_suffix = " · queued" if st.phase == "queued" else ""
        stats_suffix = self._step_stats_suffix(st)
        summary_suffix = self._step_summary_suffix(st)
        lead = f"{icon} {step_prefix}"

        def assemble(desc: str, *, include_summary: bool) -> str:
            summary = summary_suffix if include_summary else ""
            return f"{lead}{desc}{dep_suffix}{queued_suffix}{stats_suffix}{summary}"

        width = max_line_width or PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
        desc = self._clip(st.description, _MAX_GOAL_STEP_DESC)
        line = assemble(desc, include_summary=True)
        if len(line) <= width:
            return line

        line = assemble(desc, include_summary=False)
        if len(line) <= width:
            return line

        fixed_len = len(f"{lead}{dep_suffix}{queued_suffix}{stats_suffix}")
        budget = width - fixed_len
        clipped_desc = self._clip(st.description, budget)
        return f"{lead}{clipped_desc}{dep_suffix}{queued_suffix}{stats_suffix}"

    def _goal_tree_step_line_content(
        self,
        st: _StepLineState,
        *,
        max_line_width: int | None = None,
    ) -> Content:
        """One goal→step row: dim tree gutter, foreground body (parity with ``CognitionStepMessage`` tool rows)."""
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = self._indent_prefix()
        icon = self._step_icon(st)
        rest = self._fit_step_line(st, icon=icon, max_line_width=max_line_width)

        if st.phase == "pending":
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, "dim"),
            )
        if st.phase == "queued":
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, colors.cognition),
            )
        if st.phase == "running":
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, colors.foreground),
            )
        if st.phase == "error" or (st.phase == "done" and not st.success):
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, colors.error),
            )
        return Content.assemble(
            Content.styled(gutter, "dim"),
            Content.styled(rest, colors.foreground),
        )

    def _assemble_steps_content(self, *, max_line_width: int | None = None) -> Content:
        line_contents: list[Content] = []
        for sid in self._step_order:
            st = self._steps.get(sid)
            if st is None:
                continue
            line_contents.append(
                self._goal_tree_step_line_content(st, max_line_width=max_line_width)
            )
        if not line_contents:
            return Content("")
        parts: list[object] = []
        for i, c in enumerate(line_contents):
            if i:
                parts.append("\n")
            parts.append(c)
        return Content.assemble(*parts)

    def _refresh_steps_display(self) -> None:
        """Repaint mounted step/header children; no-op for overlay-only (unmounted) trees."""
        if not self.is_mounted or self._steps_static is None:
            return
        self._steps_static.update(self._assemble_steps_content())
        try:
            hdr = self.query_one("#cognition-goal-tree-header", Static)
            hdr.update(self._goal_header_content())
        except Exception:
            logger.debug("goal tree header refresh failed", exc_info=True)

    def plan_quick_view_content(self, *, max_line_width: int | None = None) -> Content:
        """Full goal tree snapshot for the Ctrl+t plan panel."""
        parts: list[object] = [self._goal_header_content()]
        steps = self._assemble_steps_content(max_line_width=max_line_width)
        if steps.plain.strip():
            parts.extend([Content("\n"), steps])
        if self._footer_visible and self._footer_plain:
            parts.extend([Content("\n"), self._goal_footer_styled_content()])
        return Content.assemble(*parts)

    def sync_running_live_stats(
        self,
        stats: dict[str, tuple[int, float | None]],
    ) -> None:
        """Update in-flight tool counts and started_at from step cards."""
        for sid, (tool_count, started_at) in stats.items():
            st = self._steps.get(sid)
            if st is None or st.phase != "running":
                continue
            st.tool_call_count = max(0, int(tool_count))
            if started_at is not None:
                st.started_at = started_at

    def tick_running_spinner(self) -> None:
        """Advance spinner frames for goal-header and running step icons.

        Live trees stay unmounted (Ctrl+t panel snapshots ``plan_quick_view_content``);
        only the spinner index is updated here. Ticks for the whole goal loop so the
        goal glyph keeps animating between steps.
        """
        if not self._loop_executing():
            return
        frames = get_glyphs().spinner_frames
        self._spinner_position = (self._spinner_position + 1) % len(frames)

    def compose(self) -> ComposeResult:
        yield Static(
            self._goal_header_content(),
            id="cognition-goal-tree-header",
            classes="cognition-goal-tree-header",
        )
        yield Static("", id="cognition-goal-tree-steps", classes="cognition-goal-tree-steps")
        yield Static("", id="cognition-goal-tree-footer", classes="cognition-goal-tree-footer")

    def on_mount(self) -> None:
        """Wire step aggregate; sync static children from in-memory state."""
        self._steps_static = self.query_one("#cognition-goal-tree-steps", Static)
        self._sync_goal_tree_widgets()

    def _sync_goal_tree_widgets(self) -> None:
        """Push goal, steps, and footer state to child widgets (requires mount)."""
        if not self.is_mounted:
            return
        try:
            ft = self.query_one("#cognition-goal-tree-footer", Static)
            if self._footer_visible and self._footer_plain:
                ft.update(self._goal_footer_styled_content())
                ft.display = True
            else:
                ft.display = False
        except Exception:
            logger.debug("goal tree footer sync failed", exc_info=True)
        # Header + steps (single path; avoids a duplicate header update).
        self._refresh_steps_display()

    def snapshot_dict(self) -> dict[str, Any]:
        """Serialize tree state for the message store."""
        steps_out: list[dict[str, Any]] = []
        for sid in self._step_order:
            st = self._steps.get(sid)
            if st is None:
                continue
            steps_out.append(
                {
                    "id": st.step_id,
                    "description": st.description,
                    "phase": st.phase,
                    "success": st.success,
                    "duration_ms": st.duration_ms,
                    "tool_call_count": st.tool_call_count,
                    "summary": st.summary,
                    "dependencies": list(st.dependencies),
                    "started_at": st.started_at,
                }
            )
        return {
            "goal": self._goal_text,
            "max_iterations": self._max_iterations,
            "execution_mode": self._execution_mode,
            "steps": steps_out,
            "footer_visible": self._footer_visible,
            "footer_text": self._footer_plain,
            "footer_tone": self._footer_tone,
            "loop_started_at": self._loop_started_at,
        }

    def _apply_snapshot(self, snap: dict[str, Any]) -> None:
        """Restore in-memory goal tree state from :meth:`snapshot_dict` output."""
        self._goal_text = str(snap.get("goal", self._goal_text))
        self._max_iterations = int(snap.get("max_iterations", self._max_iterations))
        self._execution_mode = str(snap.get("execution_mode", self._execution_mode))
        self._footer_plain = str(snap.get("footer_text", ""))
        self._footer_visible = bool(snap.get("footer_visible", False))
        tone = str(snap.get("footer_tone", "muted") or "muted")
        self._footer_tone = tone if tone in ("success", "error", "muted") else "muted"
        loop_started_raw = snap.get("loop_started_at")
        self._loop_started_at = float(loop_started_raw) if loop_started_raw is not None else None
        self._step_order = []
        self._steps.clear()
        for row in snap.get("steps", []) or []:
            sid = str(row.get("id", "")).strip()
            if not sid:
                continue
            started_raw = row.get("started_at")
            started_at = float(started_raw) if started_raw is not None else None
            st = _StepLineState(
                sid,
                str(row.get("description", "")),
                phase=str(row.get("phase", "running")),
                success=bool(row.get("success", True)),
                duration_ms=int(row.get("duration_ms", 0)),
                tool_call_count=int(row.get("tool_call_count", 0)),
                summary=str(row.get("summary", "")),
                dependencies=_normalize_step_dependencies(row.get("dependencies")),
                started_at=started_at,
            )
            self._step_order.append(sid)
            self._steps[sid] = st

    def set_execution_mode(self, mode: str) -> None:
        """Show dependency/parallel mode in the goal header."""
        self._execution_mode = (mode or "").strip()
        self._sync_goal_tree_widgets()

    def sync_plan_steps(self, steps: list[dict[str, Any]]) -> None:
        """Populate or refresh planned step rows from a plan_decision event."""
        planned_ids: set[str] = set()
        for row in steps:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("id", "")).strip()
            if not sid:
                continue
            planned_ids.add(sid)
            desc = str(row.get("description", "")).strip() or "(step)"
            deps = _normalize_step_dependencies(row.get("dependencies"))
            existing = self._steps.get(sid)
            if existing is None:
                self._step_order.append(sid)
                self._steps[sid] = _StepLineState(
                    sid,
                    desc,
                    phase="pending",
                    dependencies=deps,
                )
            elif existing.phase in ("pending", "queued"):
                existing.description = desc
                existing.dependencies = deps
            elif existing.phase == "running" and desc:
                existing.description = desc
                if deps:
                    existing.dependencies = deps
        for sid in list(self._step_order):
            st = self._steps.get(sid)
            if st is not None and st.phase == "pending" and sid not in planned_ids:
                self._step_order.remove(sid)
                del self._steps[sid]
        self._refresh_steps_display()

    def set_step_phase(
        self,
        step_id: str,
        phase: str,
        *,
        description: str | None = None,
    ) -> None:
        """Update a step row to pending, queued, or running."""
        sid = step_id.strip()
        if not sid or phase not in ("pending", "queued", "running"):
            return
        desc = (description or "").strip()
        st = self._steps.get(sid)
        if st is None:
            self._step_order.append(sid)
            st = _StepLineState(sid, desc or "(step)", phase=phase)
            self._steps[sid] = st
        else:
            if st.phase in ("done", "error"):
                return
            if phase == "pending" and st.phase in ("queued", "running"):
                return
            if phase == "queued" and st.phase == "running":
                return
            st.phase = phase
            if desc:
                st.description = desc
        if phase == "running":
            if st.started_at is None:
                st.started_at = time()
            self.mark_loop_started()
        self._refresh_steps_display()

    def complete_step(
        self,
        step_id: str,
        success: bool,
        duration_ms: int,
        tool_call_count: int,
        summary: str,
    ) -> None:
        """Update a step row to its final state."""
        sid = step_id.strip()
        if not sid:
            return
        st = self._steps.get(sid)
        if st is None:
            self._step_order.append(sid)
            st = _StepLineState(sid, "(step)", phase="running")
            self._steps[sid] = st
        st.phase = "done" if success else "error"
        st.success = success
        st.duration_ms = duration_ms
        st.tool_call_count = tool_call_count
        st.summary = summary or ""
        st.started_at = None
        self._refresh_steps_display()

    def _total_step_duration_ms(self) -> int:
        """Sum completed/errored step durations for footer fallback timing."""
        return sum(
            max(0, int(st.duration_ms))
            for st in self._steps.values()
            if st.phase in ("done", "error")
        )

    def set_loop_finished(
        self,
        *,
        status: str,
        goal_progress: str,  # IG-399: descriptive level instead of float
        completion_summary: str,
        total_steps: int,
        duration_ms: int | None = None,
    ) -> None:
        """Show a compact footer when the agentic loop completes.

        Args:
            status: Terminal status label (``done``, ``failed``, …).
            goal_progress: Descriptive progress level mapped to a percent badge.
            completion_summary: Short free-text summary clipped for the footer.
            total_steps: Completed step count shown when greater than zero.
            duration_ms: Optional wall-clock goal duration. When omitted, falls
                back to the sum of completed step durations.
        """
        # IG-399: Map descriptive levels to percentage display
        progress_map = {
            "none": "0%",
            "low": "20%",
            "medium": "50%",
            "high": "80%",
            "complete": "100%",
        }
        gp_key = str(goal_progress or "").strip().lower()
        pct_display = progress_map.get(gp_key, "0%")
        status_str = str(status or "done")
        status_str = status_str[:1].upper() + status_str[1:] if status_str else status_str
        parts: list[str] = [status_str, pct_display]
        if total_steps:
            parts.append(f"{total_steps} step(s)")
        resolved_ms = (
            int(duration_ms) if duration_ms is not None else self._total_step_duration_ms()
        )
        if resolved_ms > 0:
            parts.append(format_duration_ms(resolved_ms))
        cs = (completion_summary or "").strip()
        if cs:
            parts.append(self._clip(cs, 100))
        self._footer_plain = " · ".join(parts)
        self._footer_visible = True
        status_l = str(status or "").strip().lower()
        if status_l == "done":
            self._footer_tone = "success"
        elif status_l in ("failed", "error", "fatal"):
            self._footer_tone = "error"
        else:
            self._footer_tone = "muted"
        self._sync_goal_tree_widgets()

    def set_interrupted(self, message: str) -> None:
        """Mark running steps as failed and show a footer (stream cancel/error).

        When the loop already finished successfully and no step is still
        open, preserve the success footer (late stream-end safety net must
        not overwrite a completed goal).
        """
        msg = (message or "Interrupted").strip()
        marked = False
        for sid in list(self._step_order):
            st = self._steps.get(sid)
            if st is not None and st.phase in ("pending", "queued", "running"):
                st.phase = "error"
                st.success = False
                st.duration_ms = 0
                st.summary = msg
                st.started_at = None
                marked = True
        if not marked and self._footer_visible and self._footer_tone == "success":
            return
        self._footer_plain = self._clip(msg, 120)
        self._footer_visible = True
        self._footer_tone = "error"
        self._sync_goal_tree_widgets()
