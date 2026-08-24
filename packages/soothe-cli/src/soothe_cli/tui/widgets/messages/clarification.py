"""Clarification input message widget."""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from typing import Any, Literal

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.events import Click
from textual.message import Message
from textual.widgets import Button, Input, Static

from soothe_cli.display import theme
from soothe_cli.display.markdown_theme import ThemedMarkdownRenderer, resolve_markdown_theme_parts
from soothe_cli.settings import get_glyphs
from soothe_cli.tui.widgets.clipboard import screen_has_text_selection
from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _card_body_gutter,
)

logger = logging.getLogger(__name__)

# Wire origin id for plan-mode review (mirrors host ORIGIN_PLAN_MODE_REVIEW).
# CLI must not import soothe host packages; keep the wire string local.
_ORIGIN_PLAN_MODE_REVIEW = "plan_mode_review"


_PlanReviewAction = Literal["approve", "reject", "refine"]

_ACTION_ORDER: tuple[_PlanReviewAction, ...] = ("approve", "refine", "reject")

_ACTION_LABELS: dict[_PlanReviewAction, str] = {
    "approve": "Approve",
    "reject": "Reject",
    "refine": "Refine",
}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _strip_plan_frontmatter(markdown: str) -> str:
    """Remove YAML frontmatter from a plan artifact for display."""
    raw = (markdown or "").strip()
    if not raw.startswith("---"):
        return raw
    return _FRONTMATTER_RE.sub("", raw, count=1).strip()


class ClarificationInputMessage(Vertical):
    """Inline answer-collection widget for a pending ``ask_user`` step (RFC-622).

    Mounted when ``soothe.loop.clarification.requested`` arrives. Generic
    clarifications show one ``Input`` per question. Planner-subagent review
    (``origin_node=plan_mode_review``) shows the full draft plan, a
    saved-path footer, and Approve / Refine / Reject actions.
    """

    # Focusable so the Enter binding (expand/collapse plan body) lands on the
    # card in the submitted state, where the plan-review buttons are disabled
    # and focus would otherwise sit elsewhere.
    can_focus = True

    BINDINGS = [
        Binding("left", "plan_review_prev", "Prev action", show=False),
        Binding("right", "plan_review_next", "Next action", show=False),
        Binding("up", "plan_review_prev", "Prev action", show=False),
        Binding("down", "plan_review_next", "Next action", show=False),
        Binding("enter", "plan_review_confirm", "Confirm action", show=False),
    ]

    DEFAULT_CSS = """
    ClarificationInputMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
    }

    ClarificationInputMessage .clarification-title {
        height: auto;
        color: $warning;
        text-style: bold;
        padding: 0;
        margin: 0 0 1 0;
    }

    ClarificationInputMessage .clarification-question {
        height: auto;
        padding: 0;
        margin: 0;
        color: $text;
    }

    ClarificationInputMessage .clarification-question.has-separator {
        margin-top: 1;
    }

    ClarificationInputMessage .plan-review-body-box {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary 40%;
        background: $surface;
        overflow: hidden;
    }

    ClarificationInputMessage .plan-review-body {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0;
        color: $text;
    }

    ClarificationInputMessage .plan-review-path {
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
        color: $text-muted;
        text-style: italic;
    }

    ClarificationInputMessage .plan-review-actions {
        height: auto;
        width: 1fr;
        margin: 0;
    }

    ClarificationInputMessage .plan-review-action-row {
        height: 1;
        width: 1fr;
        margin: 0;
    }

    ClarificationInputMessage .plan-review-actions Button {
        margin: 0;
        min-width: 0;
        width: auto;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
        /* Dim grey for the non-selected option. */
        color: $text-muted 60%;
    }

    ClarificationInputMessage .plan-review-actions Button:focus {
        background: transparent;
    }

    ClarificationInputMessage .plan-review-actions Button.plan-review-selected {
        /* Bold green to make the selection obvious. */
        color: $success;
        text-style: bold;
        background: transparent;
    }

    ClarificationInputMessage .plan-review-hint {
        height: 1;
        margin: 0 0 1 0;
        color: $text-muted;
    }

    /* Match the main ChatInput visual: solid primary border on a $surface
       fill, transparent inner padding so the cursor sits where the user
       expects. */
    ClarificationInputMessage Input {
        margin: 0;
        width: 1fr;
        height: 3;
        padding: 0 1;
        background: $surface;
        border: solid $primary;
    }

    ClarificationInputMessage Input:focus {
        border: solid $primary;
    }

    /* Inline single-line entry so the Refine row stays one row tall. */
    ClarificationInputMessage Input.plan-review-refine-input {
        margin: 0 0 0 1;
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
    }

    ClarificationInputMessage.is-submitted Input {
        border: solid $success;
    }

    ClarificationInputMessage.is-submitted .plan-review-actions Button {
        /* After submit, the selected action stays bold green; the other
           dims to grey so the user's choice is visually obvious. */
        color: $text-muted 60%;
    }

    ClarificationInputMessage.is-submitted .plan-review-actions Button.plan-review-selected {
        color: $success;
        text-style: bold;
    }

    /* ── Answered (collapsed) view ────────────────────────────────────── */
    /* Hide the answered summary until submitted. */
    ClarificationInputMessage .plan-review-answered-box {
        display: none;
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
    }
    /* When submitted, hide the active review elements and show the answered summary. */
    ClarificationInputMessage.is-submitted .plan-review-body-box,
    ClarificationInputMessage.is-submitted .plan-review-path,
    ClarificationInputMessage.is-submitted .plan-review-actions,
    ClarificationInputMessage.is-submitted .plan-review-hint {
        display: none;
    }
    ClarificationInputMessage.is-submitted .plan-review-answered-box {
        display: block;
    }
    ClarificationInputMessage .plan-review-answered-action {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0;
        margin: 0;
    }
    ClarificationInputMessage .plan-review-expand-toggle {
        height: auto;
        color: $primary;
        text-style: italic;
        padding: 0;
        margin: 0;
    }
    ClarificationInputMessage.is-submitted .plan-review-body-box.is-expanded {
        display: block;
    }
    """

    class Submitted(Message):
        """Bubbles when the user finishes answering all questions."""

        def __init__(
            self,
            *,
            step_id: str,
            questions: list[str],
            answers: list[str],
            widget_id: str,
        ) -> None:
            super().__init__()
            self.step_id = step_id
            self.questions = questions
            self.answers = answers
            self.widget_id = widget_id

    def __init__(
        self,
        *,
        step_id: str,
        questions: list[str],
        widget_id: str | None = None,
        origin_node: str | None = None,
        plan_path: str | None = None,
        plan_markdown: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._step_id = step_id
        self._questions: list[str] = [q for q in questions if q.strip()]
        self._origin_node = (origin_node or "").strip()
        self._plan_path = (plan_path or "").strip()
        self._plan_markdown = (plan_markdown or "").strip()
        self._inputs: list[Input] = []
        self._submitted = False
        self._answers: list[str] = []
        self._widget_id = widget_id or self.id or ""
        self._selected_action: _PlanReviewAction = "approve"
        self._action_buttons: dict[_PlanReviewAction, Button] = {}
        self._refine_input: Input | None = None
        # Expand/collapse state for the plan body in the answered view.
        self._body_expanded = False

    @property
    def _is_plan_review(self) -> bool:
        return self._origin_node == _ORIGIN_PLAN_MODE_REVIEW

    def _title_content(self) -> Content:
        title = "Review this plan" if self._is_plan_review else "Awaiting your answer"
        if self._submitted:
            return _assemble_card_header(self, title, status="success")
        colors = theme.get_theme_colors(self)
        return _assemble_card_header(
            self,
            title,
            status="pending",
            accent=colors.warning,
        )

    def _refresh_title(self) -> None:
        try:
            title = self.query_one(".clarification-title", Static)
            title.update(self._title_content())
        except Exception:  # noqa: BLE001
            pass

    def _refresh_answered_summary(self) -> None:
        """Update the collapsed answered view with the actual action label.

        Called after ``_submitted`` is set. Also used on resume to populate the
        answered card from persisted ``MessageData`` fields.

        Each answered-view row carries the ``⎿`` tree gutter (parity with the
        goal→step tree in ``CognitionGoalTreeMessage``), so the action and the
        plan-body toggle hang off one aligned branch instead of stacking as
        disconnected stubs. Refine keeps its comment beside the action label.
        """
        if not self._answers:
            return
        gutter = _card_body_gutter()
        action = self._answers[0] if self._answers else ""
        comments = self._answers[1] if len(self._answers) > 1 else ""
        summary = f"{action}: {comments}" if action == "Refine" and comments else action
        try:
            action_w = self.query_one(".plan-review-answered-action", Static)
            action_w.update(f"{gutter}[{summary}]")
        except Exception:  # noqa: BLE001
            pass
        self._update_expand_toggle()

    def _update_expand_toggle(self) -> None:
        """Refresh the expand/collapse hint for the plan body."""
        if not self._plan_markdown.strip():
            try:
                toggle = self.query_one(".plan-review-expand-toggle", Static)
                toggle.display = False
            except Exception:  # noqa: BLE001
                pass
            return
        indent = _card_body_gutter()
        g = get_glyphs()
        try:
            toggle = self.query_one(".plan-review-expand-toggle", Static)
            if self._body_expanded:
                toggle.update(f"{indent}{g.collapse} Collapse plan body")
            else:
                line_count = self._plan_body_text.count("\n") + 1
                toggle.update(
                    f"{indent}{g.expand} Plan body ({line_count} lines) — click or press Enter to expand"
                )
        except Exception:  # noqa: BLE001
            pass

    def _toggle_body_expanded(self) -> None:
        """Expand or collapse the plan body in the answered view.

        Uses an ``is-expanded`` class on the body box so the CSS rule for the
        submitted state (``display: none``) is overridden only while expanded.
        This avoids a Python ``display`` assignment fighting the submitted-state
        CSS, which previously left the branch unexpandable.
        """
        self._body_expanded = not self._body_expanded
        try:
            body_box = self.query_one(".plan-review-body-box", Vertical)
            if self._body_expanded:
                body_box.add_class("is-expanded")
            else:
                body_box.remove_class("is-expanded")
        except Exception:  # noqa: BLE001
            pass
        self._update_expand_toggle()

    def _path_footer_text(self) -> str:
        if self._plan_path:
            return f"Plan saved to: {self._plan_path}"
        return "Plan held in memory only"

    def _compose_plan_review(self) -> Any:
        yield Static(self._title_content(), classes="clarification-title")
        # Answered summary — visible only when ``is-submitted`` (CSS toggles).
        yield from self._compose_answered_summary()
        body = _strip_plan_frontmatter(self._plan_markdown)
        # Expand to full plan height — no inner scroll; the chat list scrolls.
        with Vertical(classes="plan-review-body-box"):
            body_widget = Static("", classes="plan-review-body", markup=False)
            yield body_widget
            # Stash for on_mount markdown render (widget not yet mounted here).
            self._plan_body_widget = body_widget
            self._plan_body_text = body
        yield Static(self._path_footer_text(), classes="plan-review-path", markup=False)
        with Vertical(classes="plan-review-actions"):
            for index, action in enumerate(_ACTION_ORDER, start=1):
                with Horizontal(classes="plan-review-action-row"):
                    suffix = ":" if action == "refine" else ""
                    btn = Button(
                        f"{index}. {_ACTION_LABELS[action]}{suffix}",
                        id=f"plan-review-btn-{action}",
                        variant="default",
                        compact=True,
                    )
                    self._action_buttons[action] = btn
                    yield btn
                    if action == "refine":
                        refine_input = Input(
                            placeholder="Comments…",
                            id="plan-review-refine-comments",
                            classes="plan-review-refine-input",
                        )
                        self._refine_input = refine_input
                        yield refine_input
        yield Static("↑/↓ switch · Enter confirm", classes="plan-review-hint", markup=False)

    def _compose_answered_summary(self) -> Any:
        """Collapsed answered view: action row + expandable plan body.

        Hidden by CSS (``display: none``) until ``is-submitted`` is added; then
        the active review body / buttons / hint are hidden and this is shown.

        Each row carries the ``⎿`` tree gutter (parity with the goal→step tree),
        so the action and the plan-body toggle hang off one aligned branch — no
        stray empty stub, no repeated disconnected connectors.
        """
        gutter = _card_body_gutter()
        with Vertical(classes="plan-review-answered-box"):
            # markup=False: literal bracketed action labels would
            # otherwise be parsed by Rich as a style tag and stripped from the
            # rendered output, leaving the gutter prefix dangling on an empty
            # row.
            yield Static(
                f"{gutter}[Rejected]",
                classes="plan-review-answered-action",
                markup=False,
            )
            yield Static(
                f"{gutter}{get_glyphs().expand} Plan body — click or press Enter to expand",
                classes="plan-review-expand-toggle",
                markup=True,
            )

    def _compose_generic(self) -> Any:
        yield Static(self._title_content(), classes="clarification-title")
        for i, q in enumerate(self._questions):
            q_classes = "clarification-question"
            if i > 0:
                q_classes += " has-separator"
            yield Static(f"Q{i + 1}: {q}", classes=q_classes, markup=False)
            inp = Input(placeholder=f"Your answer for Q{i + 1}…", id=f"clarification-input-{i}")
            self._inputs.append(inp)
            yield inp

    def compose(self) -> Any:
        if self._is_plan_review:
            yield from self._compose_plan_review()
        else:
            yield from self._compose_generic()

    def on_mount(self) -> None:
        if self._is_plan_review:
            self._render_plan_body()
            if self._submitted:
                # Restored from transcript in answered state — collapse the body
                # and populate the answered summary.
                self._refresh_answered_summary()
            else:
                self._set_selected_action("approve")
                approve = self._action_buttons.get("approve")
                if approve is not None:
                    self._schedule_focus(approve)
            return
        if not self._inputs:
            return
        app = self.app
        if hasattr(app, "focus_primary_input"):
            app.focus_primary_input()
            return
        self._schedule_focus(self._inputs[0])

    def _render_plan_body(self) -> None:
        body_widget = getattr(self, "_plan_body_widget", None)
        text = getattr(self, "_plan_body_text", "") or ""
        if body_widget is None:
            with suppress(Exception):
                body_widget = self.query_one(".plan-review-body", Static)
        if body_widget is None:
            return
        if not text:
            body_widget.update("(No plan content)")
            return
        try:
            entry, colors, code_theme = resolve_markdown_theme_parts(self)
            body_widget.update(
                ThemedMarkdownRenderer(
                    text,
                    entry=entry,
                    colors=colors,
                    code_theme=code_theme,
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("Plan review markdown render failed; using plain text", exc_info=True)
            body_widget.update(text)

    def _schedule_focus(self, widget: Any) -> None:
        """Focus ``widget`` after layout settles.

        Uses ``call_after_refresh`` alone — Textual fires it exactly once
        after the next render cycle, after layout has settled. The previous
        implementation added a 50 ms ``set_timer`` fallback to win a focus
        race against ChatInput's app-level ``on_click`` / ``on_app_focus``
        handlers, but those handlers now guard against stealing focus from
        focusable widgets (``_click_landed_on_focusable`` and the
        ``focused is not None`` check in ``on_app_focus``), so the race no
        longer exists. Removing the timer also eliminates stale callbacks
        that re-focused the previously-selected menu item (block flash).
        """
        app = self.app

        def _focus() -> None:
            try:
                app.set_focus(widget)
            except Exception:  # noqa: BLE001
                try:
                    widget.focus()
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "ClarificationInputMessage: failed to focus widget",
                        exc_info=True,
                    )

        try:
            self.call_after_refresh(_focus)
        except Exception:  # noqa: BLE001
            _focus()

    def _set_selected_action(self, action: _PlanReviewAction) -> None:
        self._selected_action = action
        for key, btn in self._action_buttons.items():
            if key == action:
                btn.add_class("plan-review-selected")
            else:
                btn.remove_class("plan-review-selected")

    def _cycle_plan_review_action(self, delta: int) -> None:
        if self._submitted or not self._is_plan_review:
            return
        idx = _ACTION_ORDER.index(self._selected_action)
        action = _ACTION_ORDER[(idx + delta) % len(_ACTION_ORDER)]
        self._apply_plan_review_selection(action, activate=False)

    def _apply_plan_review_selection(self, action: _PlanReviewAction, *, activate: bool) -> None:
        self._set_selected_action(action)
        btn = self._action_buttons.get(action)
        if activate and action == "refine":
            # Keep comments inline with the Refine row.
            self._schedule_focus(self._refine_input)
        else:
            if btn is not None:
                self._schedule_focus(btn)
            if activate:
                self._finalize_plan_review(action=action)

    def on_click(self, event: Click) -> None:
        """Toggle plan body expand/collapse in the answered (submitted) view.

        Before submission, clicks are left for the plan-review buttons. After
        submission the active review elements are hidden, so a click anywhere on
        the card flips the plan body open/closed — the same action Enter performs
        via ``action_plan_review_confirm``.
        """
        if not self._is_plan_review or not self._submitted:
            return
        if screen_has_text_selection(self.screen):
            return
        event.stop()
        self._toggle_body_expanded()

    def action_plan_review_prev(self) -> None:
        """Select the previous plan-review action (←)."""
        self._cycle_plan_review_action(-1)

    def action_plan_review_next(self) -> None:
        """Select the next plan-review action (→)."""
        self._cycle_plan_review_action(1)

    def action_plan_review_confirm(self) -> None:
        """Confirm the selected plan-review action (Enter).

        After submission, Enter toggles plan body expand/collapse in the
        answered view.
        """
        if not self._is_plan_review:
            return
        if self._submitted:
            self._toggle_body_expanded()
            return
        self._apply_plan_review_selection(self._selected_action, activate=True)

    @on(Button.Pressed)
    def _on_plan_review_button(self, event: Button.Pressed) -> None:
        if self._submitted or not self._is_plan_review:
            return
        btn_id = event.button.id or ""
        action: _PlanReviewAction | None = None
        if btn_id == "plan-review-btn-approve":
            action = "approve"
        elif btn_id == "plan-review-btn-reject":
            action = "reject"
        elif btn_id == "plan-review-btn-refine":
            action = "refine"
        if action is None:
            return
        event.stop()
        # Click selects and activates the action.
        self._apply_plan_review_selection(action, activate=True)

    @on(Input.Submitted)
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if self._submitted:
            event.stop()
            return
        if self._is_plan_review:
            if event.input is self._refine_input:
                comments = str(event.input.value or "").strip()
                if comments:
                    self._finalize_plan_review_with_comments(comments)
                event.stop()
            return
        idx = self._inputs.index(event.input) if event.input in self._inputs else -1
        if idx < 0:
            return
        # Move to the next blank field if any are still empty; otherwise finalize.
        next_blank = next(
            (
                j
                for j, inp in enumerate(self._inputs)
                if j != idx and not str(inp.value or "").strip()
            ),
            None,
        )
        if next_blank is not None:
            try:
                self._inputs[next_blank].focus()
            except Exception:  # noqa: BLE001
                logger.debug("ClarificationInputMessage: focus next blank failed", exc_info=True)
            event.stop()
            return
        self._finalize()
        event.stop()

    def _finalize_plan_review(self, *, action: _PlanReviewAction) -> None:
        if self._submitted:
            return
        label = _ACTION_LABELS[action]
        answers = [label, ""]
        self._submitted = True
        self._answers = answers
        for btn in self._action_buttons.values():
            btn.disabled = True
        if self._refine_input is not None:
            self._refine_input.disabled = True
        self.add_class("is-submitted")
        self._refresh_title()
        self._refresh_answered_summary()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=list(self._questions),
                answers=answers,
                widget_id=self._widget_id,
            )
        )

    def _finalize_plan_review_with_comments(self, comments: str) -> None:
        """Finalize a refinement request with the user's comments.

        Called when the user types text after selecting Refine. The comments
        become the second answer so the daemon's refinement re-synthesis
        picks them up.
        """
        if self._submitted:
            return
        answers = ["Refine", comments]
        self._submitted = True
        self._answers = answers
        for btn in self._action_buttons.values():
            btn.disabled = True
        if self._refine_input is not None:
            self._refine_input.disabled = True
        self.add_class("is-submitted")
        self._refresh_title()
        self._refresh_answered_summary()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=list(self._questions),
                answers=answers,
                widget_id=self._widget_id,
            )
        )

    def _finalize(self) -> None:
        if self._submitted:
            return
        raw = [str(inp.value or "").strip() for inp in self._inputs]
        # Broadcast a single non-empty answer to all questions when the user
        # only filled one field.
        non_empty = [a for a in raw if a]
        if len(non_empty) == 1 and len(raw) > 1:
            answers = non_empty * len(raw)
        else:
            answers = raw
        if not any(answers):
            return
        self._submitted = True
        self._answers = answers
        for inp in self._inputs:
            inp.disabled = True
        self.add_class("is-submitted")
        self._refresh_title()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=list(self._questions),
                answers=answers,
                widget_id=self._widget_id,
            )
        )
