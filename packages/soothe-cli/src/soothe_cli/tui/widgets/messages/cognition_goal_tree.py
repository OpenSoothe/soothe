"""Cognition goal tree message widget."""

from __future__ import annotations

import logging
import re
from time import time
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from soothe_cli.display import theme
from soothe_cli.display.preview_limits import PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
from soothe_cli.runtime.presentation.duration_format import (
    format_duration,
    format_duration_ms,
    format_running_elapsed,
)
from soothe_cli.runtime.presentation.step_id_format import (
    display_step_id,
    numeric_step_prefix,
)
from soothe_cli.settings import get_glyphs
from soothe_cli.tui.widgets.messages._helpers import (
    _card_body_gutter,
    _card_dot_prefix_content,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


# Host may send an execute-phase complexity (``minimal``/``simple``/``complex``)
# or a routing label (``minimal``/``simple``/``complex``).
_INTAKE_LABELS = frozenset({"minimal", "simple", "complex"})

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
    parts = [numeric_step_prefix(dep) for dep in shown]
    text = ", ".join(p for p in parts if p)
    if len(deps) > _MAX_DEPENDENCY_IDS:
        text += ", …"
    return f" (→ {text})" if text else ""


def _plan_quick_view_step_summary(
    success: bool,
    summary: str,
    *,
    tool_call_count: int = 0,
) -> str:
    """Return a Ctrl+T-safe step summary tail.

    Hides redundant `Done [N tools]` text (stats already show tool count) and
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
        "input_tokens",
        "output_tokens",
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
        input_tokens: int = 0,
        output_tokens: int = 0,
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
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class CognitionGoalTreeMessage(Vertical):
    """Two-level Goal → steps tree; one aggregate block updates in place.

    Title line matches `CognitionStepMessage` / `CognitionReasonMessage`:
    stateful card-prefix glyph plus goal text.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionGoalTreeMessage {
        height: auto;
        padding: 0 1;
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
        max_iterations: Retained for snapshot/restore parity; not rendered.
        **kwargs: Passed to `Vertical`.
        """
        super().__init__(**kwargs)
        self._goal_text = goal.strip()
        self._max_iterations = int(max_iterations)
        self._step_order: list[str] = []
        self._steps: dict[str, _StepLineState] = {}
        self._footer_plain: str = ""
        self._footer_visible: bool = False
        self._footer_tone: str = "muted"  # success | error | muted (step/tool completion parity)
        self._intake_label: str = ""
        self._spinner_position: int = 0
        self._loop_started_at: float | None = None
        self._steps_static: Static | None = None
        # Goal-level accumulator for orphan usage chunks that arrive before any
        # step card is bound (parallel waves). ``goal_token_totals`` sums these
        # with per-step tokens so no usage chunk is silently dropped.
        self._goal_in_tokens: int = 0
        self._goal_out_tokens: int = 0

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

    def plan_panel_prefix_content(self) -> Content:
        """Goal lifecycle glyph for the plan panel title (and restored tree header)."""
        return _card_dot_prefix_content(
            self,
            self._goal_tree_status(),
            glyph_override=get_glyphs().subagent_prefix,
            spinner_position=self._spinner_position,
            animate_running=self._loop_executing(),
        )

    def intake_label(self) -> str:
        """Intake complexity, or empty when the host sent no usable value."""
        return self._intake_label

    def _goal_header_content(self) -> Content:
        """Goal title for restored/mounted tree cards (not the live plan panel).

        Live trees stay unmounted; the Ctrl+t panel title uses
        `plan_panel_prefix_content` + `_plan_quick_view_header` instead.
        """
        body = self._clip(self._goal_text, _MAX_GOAL_HEADER)
        intake = self.intake_label()
        if intake:
            body = f"{body} · {intake}"
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        return Content.assemble(
            self.plan_panel_prefix_content(),
            Content.styled(body, colors.foreground),
        )

    def _goal_footer_styled_content(self) -> Content:
        """Footer content for loop finished / interrupted (parity with step/tool status lines).

        The `done` (success) footer shares the title line's de-emphasized
        `SECONDARY_TEXT_STYLE` so the completion status blends with the
        "Orchestrating ..." header instead of using the cognition accent.
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

    def goal_token_totals(self) -> tuple[int, int]:
        """Cumulative `(input_tokens, output_tokens)` across all step rows.

        Includes goal-level orphan usage (parallel-wave `usage_metadata`
        chunks that arrived before any step card was bound) so no usage chunk
        is silently dropped from the totals.
        """
        total_in = self._goal_in_tokens
        total_out = self._goal_out_tokens
        for st in self._steps.values():
            total_in += max(0, int(st.input_tokens))
            total_out += max(0, int(st.output_tokens))
        return total_in, total_out

    def record_goal_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate orphan LLM token usage at the goal level.

        Used by the adapter fallback path in `_resolve_token_target_card`
        when a `usage_metadata` chunk arrives under a namespace that cannot
        be bound to a step card (parallel waves where usage precedes any tool
        call). Routes the chunk to the goal-level accumulator instead of
        dropping it, so it surfaces in `goal_token_totals` / the done footer.
        """
        in_t = max(0, int(input_tokens))
        out_t = max(0, int(output_tokens))
        if not in_t and not out_t:
            return
        self._goal_in_tokens += in_t
        self._goal_out_tokens += out_t

    def goal_token_suffix(self) -> str:
        """Compact `↑1.2K ↓345` suffix for the plan panel title.

        Returns an empty string when no step has recorded any tokens.
        """
        total_in, total_out = self.goal_token_totals()
        if not (total_in or total_out):
            return ""
        from soothe_cli.runtime.state.session_stats import format_token_count

        return f"↑{format_token_count(total_in)} ↓{format_token_count(total_out)}"

    def mark_loop_started(self, started_at: float | None = None) -> None:
        """Anchor plan-level elapsed time (matches thinking-row turn start)."""
        if self._loop_started_at is None:
            self._loop_started_at = started_at if started_at is not None else time()

    def _indent_prefix(self) -> str:
        """Body gutter aligned to the right of the goal header prefix dot.

        The goal header uses the subagent glyph, so the body gutter pads to that
        prefix width (see :func:`_card_body_gutter`); every step row therefore
        left-aligns at the right side of the dot space.
        """
        return _card_body_gutter(get_glyphs().subagent_prefix)

    def _step_icon(self, st: _StepLineState) -> str:
        g = get_glyphs()
        if st.phase == "pending" or st.phase == "queued":
            return g.circle_empty
        if st.phase == "running":
            frames = g.spinner_frames
            return frames[self._spinner_position % len(frames)]
        return g.checkmark if st.success else g.error

    def _step_stats_suffix(self, st: _StepLineState) -> str:
        """Duration, tool-count, and token suffix for running or completed rows."""
        token_parts = self._step_token_parts(st)
        if st.phase == "running":
            parts: list[str] = []
            if st.started_at is not None:
                # Middot-separated live timer (matches step-card title elapsed meta).
                parts.append(format_running_elapsed(time() - st.started_at))
            if st.tool_call_count > 0:
                parts.append(f"{st.tool_call_count} tools")
            parts.extend(token_parts)
            if not parts:
                return ""
            return " · " + " · ".join(parts)
        if st.phase not in ("done", "error"):
            return ""
        dur_s = max(0.001, st.duration_ms / 1000.0)
        parts = [format_duration(dur_s)]
        if st.tool_call_count > 0:
            parts.append(f"{st.tool_call_count} tools")
        parts.extend(token_parts)
        return " · " + " · ".join(parts)

    @staticmethod
    def _step_token_parts(st: _StepLineState) -> list[str]:
        """Arrow token labels for a step row, e.g. `↑1.2K ↓345`."""
        if not (st.input_tokens or st.output_tokens):
            return []
        from soothe_cli.runtime.state.session_stats import format_token_count

        return [
            f"↑{format_token_count(st.input_tokens)}",
            f"↓{format_token_count(st.output_tokens)}",
        ]

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
        """Build a single-line step row, clipping description to fit `max_line_width`."""
        step_label = display_step_id(st.step_id)
        step_prefix = f"{step_label}: " if step_label else ""
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
        """One goal→step row: dim tree gutter, foreground body (parity with `CognitionStepMessage` tool rows)."""
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
        """Step rows (plus terminal footer) for the Ctrl+t plan panel body.

        Omits the goal title line: the overlay header carries the short loop
        id, intake complexity, and elapsed time via `_plan_quick_view_header`.
        """
        parts: list[object] = []
        steps = self._assemble_steps_content(max_line_width=max_line_width)
        if steps.plain.strip():
            parts.append(steps)
        if self._footer_visible and self._footer_plain:
            if parts:
                parts.append(Content("\n"))
            parts.append(self._goal_footer_styled_content())
        return Content.assemble(*parts)

    def sync_running_live_stats(
        self,
        stats: dict[str, tuple[int, float | None, int, int]],
    ) -> None:
        """Update in-flight tool counts, start times, and token counts from step cards.

        Each value is `(tool_count, started_at, input_tokens, output_tokens)`.
        """
        for sid, (tool_count, started_at, input_tokens, output_tokens) in stats.items():
            st = self._steps.get(sid)
            if st is None or st.phase != "running":
                continue
            st.tool_call_count = max(0, int(tool_count))
            if started_at is not None:
                st.started_at = started_at
            st.input_tokens = max(0, int(input_tokens))
            st.output_tokens = max(0, int(output_tokens))

    def tick_running_spinner(self) -> None:
        """Advance spinner frames for goal-header and running step icons.

        Live trees stay unmounted (Ctrl+t panel snapshots `plan_quick_view_content`);
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
                    "input_tokens": st.input_tokens,
                    "output_tokens": st.output_tokens,
                }
            )
        return {
            "goal": self._goal_text,
            "max_iterations": self._max_iterations,
            "intake_label": self._intake_label,
            "steps": steps_out,
            "footer_visible": self._footer_visible,
            "footer_text": self._footer_plain,
            "footer_tone": self._footer_tone,
            "loop_started_at": self._loop_started_at,
            "goal_in_tokens": self._goal_in_tokens,
            "goal_out_tokens": self._goal_out_tokens,
        }

    def _apply_snapshot(self, snap: dict[str, Any]) -> None:
        """Restore in-memory goal tree state from :meth:`snapshot_dict` output."""
        self._goal_text = str(snap.get("goal", self._goal_text))
        self._max_iterations = int(snap.get("max_iterations", self._max_iterations))
        raw_intake = str(snap.get("intake_label", "") or "").strip().lower()
        if raw_intake in _INTAKE_LABELS:
            self._intake_label = raw_intake
        self._footer_plain = str(snap.get("footer_text", ""))
        self._footer_visible = bool(snap.get("footer_visible", False))
        tone = str(snap.get("footer_tone", "muted") or "muted")
        self._footer_tone = tone if tone in ("success", "error", "muted") else "muted"
        loop_started_raw = snap.get("loop_started_at")
        self._loop_started_at = float(loop_started_raw) if loop_started_raw is not None else None
        self._goal_in_tokens = max(0, int(snap.get("goal_in_tokens", 0)))
        self._goal_out_tokens = max(0, int(snap.get("goal_out_tokens", 0)))
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
                input_tokens=int(row.get("input_tokens", 0)),
                output_tokens=int(row.get("output_tokens", 0)),
            )
            self._step_order.append(sid)
            self._steps[sid] = st

    def set_intake_label(self, label: str) -> None:
        """Show intake complexity in the goal header."""
        normalized = (label or "").strip().lower()
        if normalized not in _INTAKE_LABELS:
            return
        self._intake_label = normalized
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
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
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
        st.input_tokens = max(0, int(input_tokens))
        st.output_tokens = max(0, int(output_tokens))
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
        goal_progress: str,  # descriptive level instead of float
        completion_summary: str,
        total_steps: int,
        duration_ms: int | None = None,
    ) -> None:
        """Show a compact footer when the agentic loop completes.

        Args:
        status: Terminal status label (`done`, `failed`, …).
        goal_progress: Descriptive progress level mapped to a percent badge.
        completion_summary: Short free-text summary clipped for the footer.
        total_steps: Completed step count shown when greater than zero.
        duration_ms: Optional wall-clock goal duration. When omitted, falls
        back to the sum of completed step durations.
        """
        # Map descriptive levels to percentage display
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
        # Append cumulative token suffix (parity with step rows / panel header).
        # ``goal_token_suffix`` returns "" when no tokens recorded, so the footer
        # stays clean for token-less runs.
        token_suffix = self.goal_token_suffix()
        if token_suffix:
            parts.append(token_suffix)
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
