"""Cognition goal tree message widget."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from soothe_cli.runtime.presentation.duration_format import format_duration
from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs, is_ascii_mode
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

_MAX_GOAL_HEADER = 100
_MAX_GOAL_STEP_DESC = 200


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
    ) -> None:
        self.step_id = step_id
        self.description = description
        self.phase = phase
        self.success = success
        self.duration_ms = duration_ms
        self.tool_call_count = tool_call_count
        self.summary = summary


class CognitionGoalTreeMessage(Vertical):
    """Two-level Goal → steps tree; one aggregate block updates in place.

    Title line matches ``CognitionStepMessage`` / ``CognitionReasonMessage``:
    ``{prefix} 📍 …`` with optional ``· iter<=N`` when ``max_iterations`` is set.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionGoalTreeMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
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

    CognitionGoalTreeMessage:hover {
        border-left: wide $cognition-hover;
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
        self._steps_static: Static | None = None

    @staticmethod
    def _clip(text: str, max_len: int) -> str:
        t = (text or "").strip().replace("\n", " ")
        if len(t) <= max_len:
            return t
        return t[: max_len - 1].rstrip() + "…"

    def _goal_header_content(self) -> Content:
        g = self._clip(self._goal_text, _MAX_GOAL_HEADER)
        body = g
        if self._max_iterations > 1:
            body = f"{body} · iter<={self._max_iterations}"
        return _assemble_card_header(self, "📍 ", body)

    def _goal_footer_styled_content(self) -> Content:
        """Footer content for loop finished / interrupted (parity with step/tool status lines)."""
        if not self._footer_visible or not self._footer_plain:
            return Content("")
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = f"{get_glyphs().output_prefix} "
        plain = self._footer_plain
        if self._footer_tone == "success":
            mark = get_glyphs().checkmark
            return Content.styled(f"{gutter}{mark} {plain}", colors.cognition)
        if self._footer_tone == "error":
            mark = get_glyphs().error
            return Content.styled(f"{gutter}{mark} {plain}", colors.error)
        return Content.styled(f"{gutter}{plain}", "dim")

    def _indent_prefix(self) -> str:
        g = get_glyphs()
        return f"{g.output_prefix} "

    def _goal_tree_step_line_content(self, st: _StepLineState) -> Content:
        """One goal→step row: dim tree gutter, foreground body (parity with ``CognitionStepMessage`` tool rows)."""
        g = get_glyphs()
        try:
            colors = theme.get_theme_colors(self)
        except Exception:  # noqa: BLE001
            colors = theme.DARK_COLORS
        gutter = self._indent_prefix()
        body = self._clip(st.description, _MAX_GOAL_STEP_DESC)
        if st.phase == "running":
            rest = f"{g.circle_empty} {body}"
        else:
            icon = g.checkmark if st.success else g.error
            dur_s = max(0.001, st.duration_ms / 1000.0)
            dur = format_duration(dur_s)
            rest = f"{icon} {body} · {dur}"
            if st.tool_call_count > 0:
                rest += f" · {st.tool_call_count} tools"
            tail = (st.summary or "").strip()
            if tail and tail not in ("Done", "Failed"):
                rest += f" — {self._clip(tail, 80)}"
        if st.phase == "error" or (st.phase == "done" and not st.success):
            return Content.assemble(
                Content.styled(gutter, "dim"),
                Content.styled(rest, colors.error),
            )
        return Content.assemble(
            Content.styled(gutter, "dim"),
            Content.styled(rest, colors.foreground),
        )

    def _refresh_steps_display(self) -> None:
        if self._steps_static is None:
            return
        line_contents: list[Content] = []
        for sid in self._step_order:
            st = self._steps.get(sid)
            if st is None:
                continue
            line_contents.append(self._goal_tree_step_line_content(st))
        if not line_contents:
            self._steps_static.update(Content(""))
            return
        parts: list[object] = []
        for i, c in enumerate(line_contents):
            if i:
                parts.append("\n")
            parts.append(c)
        self._steps_static.update(Content.assemble(*parts))

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
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
        self._sync_goal_tree_widgets()

    def _sync_goal_tree_widgets(self) -> None:
        """Push goal, steps, and footer state to child widgets (requires mount)."""
        try:
            hdr = self.query_one("#cognition-goal-tree-header", Static)
            hdr.update(self._goal_header_content())
        except Exception:
            logger.debug("goal tree header sync failed", exc_info=True)
        try:
            ft = self.query_one("#cognition-goal-tree-footer", Static)
            if self._footer_visible and self._footer_plain:
                ft.update(self._goal_footer_styled_content())
                ft.display = True
            else:
                ft.display = False
        except Exception:
            logger.debug("goal tree footer sync failed", exc_info=True)
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
                }
            )
        return {
            "goal": self._goal_text,
            "max_iterations": self._max_iterations,
            "steps": steps_out,
            "footer_visible": self._footer_visible,
            "footer_text": self._footer_plain,
            "footer_tone": self._footer_tone,
        }

    def _apply_snapshot(self, snap: dict[str, Any]) -> None:
        """Restore in-memory goal tree state from :meth:`snapshot_dict` output."""
        self._goal_text = str(snap.get("goal", self._goal_text))
        self._max_iterations = int(snap.get("max_iterations", self._max_iterations))
        self._footer_plain = str(snap.get("footer_text", ""))
        self._footer_visible = bool(snap.get("footer_visible", False))
        tone = str(snap.get("footer_tone", "muted") or "muted")
        self._footer_tone = tone if tone in ("success", "error", "muted") else "muted"
        self._step_order = []
        self._steps.clear()
        for row in snap.get("steps", []) or []:
            sid = str(row.get("id", "")).strip()
            if not sid:
                continue
            st = _StepLineState(
                sid,
                str(row.get("description", "")),
                phase=str(row.get("phase", "running")),
                success=bool(row.get("success", True)),
                duration_ms=int(row.get("duration_ms", 0)),
                tool_call_count=int(row.get("tool_call_count", 0)),
                summary=str(row.get("summary", "")),
            )
            self._step_order.append(sid)
            self._steps[sid] = st

    def add_step_running(self, step_id: str, description: str) -> None:
        """Register a step in running state and refresh the aggregate."""
        sid = step_id.strip()
        if not sid:
            return
        desc = (description or "").strip() or "(step)"
        if sid not in self._steps:
            self._step_order.append(sid)
        self._steps[sid] = _StepLineState(sid, desc, phase="running")
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
        self._refresh_steps_display()

    def set_loop_finished(
        self,
        *,
        status: str,
        goal_progress: str,  # IG-399: descriptive level instead of float
        completion_summary: str,
        total_steps: int,
    ) -> None:
        """Show a compact footer when the agentic loop completes."""
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
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(self._goal_footer_styled_content())
            footer.display = True
        except Exception:
            pass

    def set_interrupted(self, message: str) -> None:
        """Mark running steps as failed and show a footer (stream cancel/error)."""
        msg = (message or "Interrupted").strip()
        for sid in list(self._step_order):
            st = self._steps.get(sid)
            if st is not None and st.phase == "running":
                st.phase = "error"
                st.success = False
                st.duration_ms = 0
                st.summary = msg
        self._refresh_steps_display()
        self._footer_plain = self._clip(msg, 120)
        self._footer_visible = True
        self._footer_tone = "error"
        try:
            footer = self.query_one("#cognition-goal-tree-footer", Static)
            footer.update(self._goal_footer_styled_content())
            footer.display = True
        except Exception:
            pass
