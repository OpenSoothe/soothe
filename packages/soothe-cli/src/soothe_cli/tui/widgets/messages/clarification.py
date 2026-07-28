"""Clarification input message widget."""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from typing import Any, Literal

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, Input, Static

from soothe_cli.tui import theme
from soothe_cli.tui.markdown_theme import ThemedMarkdownRenderer, resolve_markdown_theme_parts
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

logger = logging.getLogger(__name__)

# Wire origin id for planner-subagent review (mirrors host ORIGIN_PLANNER_SUBAGENT_REVIEW).
# CLI must not import soothe host packages; keep the wire string local.
_ORIGIN_PLANNER_SUBAGENT_REVIEW = "planner_subagent_review"

_PlanReviewAction = Literal["approve", "reject", "comments"]

_ACTION_LABELS: dict[_PlanReviewAction, str] = {
    "approve": "Approve",
    "reject": "Reject",
    "comments": "More comments",
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
    (``origin_node=planner_subagent_review``) shows the full draft plan, a
    saved-path footer, Approve / Reject / More comments actions, and a
    comments field only after More comments is selected.
    """

    DEFAULT_CSS = """
    ClarificationInputMessage {
        height: auto;
        padding: 0;
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

    ClarificationInputMessage .plan-review-body-scroll {
        height: auto;
        max-height: 24;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary 40%;
        background: $surface;
    }

    ClarificationInputMessage .plan-review-body {
        height: auto;
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
        width: 100%;
        margin: 0 0 1 0;
    }

    ClarificationInputMessage .plan-review-actions Button {
        margin: 0 1 0 0;
        min-width: 14;
    }

    ClarificationInputMessage .plan-review-actions Button.plan-review-selected {
        text-style: bold;
        border: solid $warning;
    }

    ClarificationInputMessage .plan-review-comments.hidden {
        display: none;
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

    ClarificationInputMessage.is-submitted Input {
        border: solid $success;
    }

    ClarificationInputMessage.is-submitted .plan-review-actions Button {
        border: solid $success;
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
        self._selected_action: _PlanReviewAction | None = None
        self._comments_input: Input | None = None
        self._action_buttons: dict[_PlanReviewAction, Button] = {}

    @property
    def _is_planner_subagent_review(self) -> bool:
        return self._origin_node == _ORIGIN_PLANNER_SUBAGENT_REVIEW

    def _title_content(self) -> Content:
        title = "Review this plan" if self._is_planner_subagent_review else "Awaiting your answer"
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

    def _path_footer_text(self) -> str:
        if self._plan_path:
            return f"Plan saved to: {self._plan_path}"
        return "Plan held in memory only"

    def _compose_planner_review(self) -> Any:
        yield Static(self._title_content(), classes="clarification-title")
        body = _strip_plan_frontmatter(self._plan_markdown)
        with VerticalScroll(classes="plan-review-body-scroll"):
            body_widget = Static("", classes="plan-review-body", markup=False)
            yield body_widget
            # Stash for on_mount markdown render (widget not yet mounted here).
            self._plan_body_widget = body_widget
            self._plan_body_text = body
        yield Static(self._path_footer_text(), classes="plan-review-path", markup=False)
        with Horizontal(classes="plan-review-actions"):
            for action, label in _ACTION_LABELS.items():
                btn = Button(label, id=f"plan-review-btn-{action}", variant="default")
                self._action_buttons[action] = btn
                yield btn
        comments = Input(
            placeholder="Describe what to change…",
            id="plan-review-comments-input",
            classes="plan-review-comments hidden",
        )
        self._comments_input = comments
        yield comments

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
        if self._is_planner_subagent_review:
            yield from self._compose_planner_review()
        else:
            yield from self._compose_generic()

    def on_mount(self) -> None:
        if self._is_planner_subagent_review:
            self._render_plan_body()
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
        with suppress(Exception):
            self.set_timer(0.05, _focus)

    def _set_selected_action(self, action: _PlanReviewAction) -> None:
        self._selected_action = action
        for key, btn in self._action_buttons.items():
            if key == action:
                btn.add_class("plan-review-selected")
            else:
                btn.remove_class("plan-review-selected")

    def _show_comments(self, *, show: bool) -> None:
        comments = self._comments_input
        if comments is None:
            return
        if show:
            comments.remove_class("hidden")
            if comments not in self._inputs:
                self._inputs = [comments]
            self._schedule_focus(comments)
        else:
            comments.add_class("hidden")
            self._inputs = []

    @on(Button.Pressed)
    def _on_plan_review_button(self, event: Button.Pressed) -> None:
        if self._submitted or not self._is_planner_subagent_review:
            return
        btn_id = event.button.id or ""
        action: _PlanReviewAction | None = None
        if btn_id == "plan-review-btn-approve":
            action = "approve"
        elif btn_id == "plan-review-btn-reject":
            action = "reject"
        elif btn_id == "plan-review-btn-comments":
            action = "comments"
        if action is None:
            return
        event.stop()
        self._set_selected_action(action)
        if action in {"approve", "reject"}:
            self._show_comments(show=False)
            self._finalize_plan_review(action=action, comments="")
            return
        self._show_comments(show=True)

    @on(Input.Submitted)
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if self._submitted:
            event.stop()
            return
        if self._is_planner_subagent_review:
            if event.input is not self._comments_input:
                return
            if self._selected_action != "comments":
                event.stop()
                return
            comments = str(event.input.value or "").strip()
            if not comments:
                event.stop()
                return
            self._finalize_plan_review(action="comments", comments=comments)
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

    def _finalize_plan_review(self, *, action: _PlanReviewAction, comments: str) -> None:
        if self._submitted:
            return
        label = _ACTION_LABELS[action]
        answers = [label, comments]
        self._submitted = True
        self._answers = answers
        for inp in self._inputs:
            inp.disabled = True
        for btn in self._action_buttons.values():
            btn.disabled = True
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
