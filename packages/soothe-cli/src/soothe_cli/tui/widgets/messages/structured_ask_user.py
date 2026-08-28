"""Structured multi-question option-picker widget for `ask_user` and HITL gates.

Unifies the generic ``ask_user`` (execute origin) and the HITL plan-review /
tool-approval origins into one widget. HITL origins differ only in that their
options are system-prefilled (Approve / Refine or Edit / Reject), the ``Other``
free-text row is suppressed, and the Refine/Edit option shows a comment input.
"""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from typing import Any

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.events import Click, DescendantFocus
from textual.message import Message
from textual.widgets import Button, Input, Static

from soothe_cli.display import theme
from soothe_cli.display.markdown_theme import (
    ThemedMarkdownRenderer,
    resolve_markdown_theme_parts,
)
from soothe_cli.settings import get_glyphs
from soothe_cli.tui.widgets.clipboard import screen_has_text_selection
from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _card_body_gutter,
)

logger = logging.getLogger(__name__)

# Wire origin constants (mirror host ORIGIN_* constants). CLI must not import
# soothe host packages; keep the wire strings local.
_ORIGIN_EXECUTE = "execute"
_ORIGIN_PLAN_MODE_REVIEW = "plan_mode_review"
_ORIGIN_TOOL_APPROVAL = "tool_approval"

_HITL_ORIGINS: frozenset[str] = frozenset({_ORIGIN_PLAN_MODE_REVIEW, _ORIGIN_TOOL_APPROVAL})

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _strip_plan_frontmatter(markdown: str) -> str:
    """Remove YAML frontmatter from a plan artifact for display."""
    raw = (markdown or "").strip()
    if not raw.startswith("---"):
        return raw
    return _FRONTMATTER_RE.sub("", raw, count=1).strip()


class StructuredAskUserWidget(Vertical):
    """Unified multi-question option-picker for ``ask_user`` and HITL gates.

    Three modes:
    - **Structured** (default): tabs + options + hover-preview + footer.
      Used for generic ``ask_user`` (execute origin) with LLM-emitted options.
    - **HITL**: same structured layout but ``allow_custom=False`` (no "Other"
      row), origin-aware title, optional plan body rendering, and a comment
      field tied to the Refine/Edit option. Used for ``plan_mode_review``
      and ``tool_approval`` origins.
    - **Degraded**: plain free-text ``Input`` per question + Submit button.
      Used for in-flight plain-string questions from before the schema upgrade.
    """

    can_focus = True

    BINDINGS = [
        Binding("left", "prev_question", "Prev question", show=False),
        Binding("right", "next_question", "Next question", show=False),
        Binding("up", "prev_option", "Prev option", show=False),
        Binding("down", "next_option", "Next option", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
        Binding("tab", "focus_footer", "Footer", show=False),
        Binding("escape", "abandon", "Abandon", show=False),
    ]

    DEFAULT_CSS = """
    StructuredAskUserWidget {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
    }

    StructuredAskUserWidget .saq-title {
        height: auto;
        color: $warning;
        text-style: bold;
        padding: 0;
        margin: 0 0 1 0;
    }

    StructuredAskUserWidget .saq-tab-bar {
        height: auto;
        margin: 0 0 1 0;
    }

    /* height: auto is required — Vertical defaults to 1fr, which collapses
    content when the widget is mounted in a stream/auto-height container
    (e.g. #messages), crushing the description and option rows to zero. */
    StructuredAskUserWidget .saq-question-body {
        height: auto;
    }

    StructuredAskUserWidget .saq-option-list {
        height: auto;
    }

    StructuredAskUserWidget .saq-tab {
        height: 1;
        min-width: 0;
        width: auto;
        padding: 0 1;
        margin: 0 1 0 0;
        color: $text-muted;
    }

    StructuredAskUserWidget .saq-tab.is-active {
        color: $primary;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-tab.is-answered {
        color: $success;
    }

    StructuredAskUserWidget .saq-tab.is-active.is-answered {
        color: $success;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-question-title {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0;
        margin: 0 0 0 0;
    }

    StructuredAskUserWidget .saq-description {
        height: auto;
        color: $text;
        padding: 0;
        margin: 0 0 1 0;
    }

    StructuredAskUserWidget .saq-option-row {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0;
        color: $text;
    }

    StructuredAskUserWidget .saq-option-row.is-highlighted {
        color: $text;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-option-row.is-selected {
        color: $success;
        text-style: bold;
    }

    /* Long description rendered directly below each option label. */
    StructuredAskUserWidget .saq-option-desc {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0 0 1 0;
        color: $text-muted;
    }

    /* Hide stale option/desc rows when switching to a question with
    fewer options than the initially rendered one. */
    StructuredAskUserWidget .saq-option-row.is-hidden,
    StructuredAskUserWidget .saq-option-desc.is-hidden {
        display: none;
    }

    StructuredAskUserWidget .saq-custom-input {
        margin: 0 0 0 2;
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $surface;
        border: none;
    }

    StructuredAskUserWidget .saq-custom-input:disabled {
        opacity: 0.5;
    }

    StructuredAskUserWidget .saq-custom-hint {
        display: none;
        height: auto;
        padding: 0;
        margin: 0 0 0 2;
        color: $warning 80%;
        text-style: italic;
    }

    StructuredAskUserWidget .saq-custom-hint.is-visible {
        display: block;
    }

    StructuredAskUserWidget .saq-footer {
        height: 1;
        margin: 1 0 0 0;
    }

    StructuredAskUserWidget .saq-count {
        height: 1;
        padding: 0;
        margin: 0 1 0 0;
        color: $text-muted;
    }

    /* Keyboard hint shown next to the count once every question is answered. */
    StructuredAskUserWidget .saq-enter-hint {
        display: none;
        height: 1;
        padding: 0;
        margin: 0 1 0 0;
        color: $success;
    }

    StructuredAskUserWidget .saq-enter-hint.is-visible {
        display: block;
    }

    StructuredAskUserWidget .saq-footer Button {
        margin: 0;
        min-width: 0;
        width: auto;
        height: 1;
        padding: 0 1;
        border: none;
        background: transparent;
        color: $text-muted;
    }

    StructuredAskUserWidget .saq-footer Button:focus {
        color: $primary;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-footer Button.is-disabled {
        opacity: 0.4;
    }

    StructuredAskUserWidget .saq-recap {
        display: none;
        height: auto;
        padding: 0 0 0 2;
        margin: 1 0 0 0;
        color: $text;
    }

    StructuredAskUserWidget .saq-recap.is-visible {
        display: block;
    }

    StructuredAskUserWidget .saq-recap-title {
        text-style: bold;
        color: $text-muted;
        margin: 0 0 0 0;
    }

    StructuredAskUserWidget .saq-recap-row {
        height: auto;
        padding: 0;
        margin: 0;
        color: $text;
    }

    /* Horizontal rule separating the QA widget from surrounding transcript. */
    StructuredAskUserWidget .saq-separator {
        height: 1;
        color: $text-muted 30%;
        padding: 0;
        margin: 1 0 1 0;
    }

    StructuredAskUserWidget .saq-hint {
        height: 1;
        margin: 0 0 1 0;
        color: $text-muted;
    }

    /* Degraded mode */
    StructuredAskUserWidget .saq-degraded-input {
        margin: 0;
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $surface;
        border: none;
    }

    /* Submitted (collapsed) view */
    StructuredAskUserWidget .saq-answered-box {
        display: none;
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
    }

    StructuredAskUserWidget.is-submitted .saq-tab-bar,
    StructuredAskUserWidget.is-submitted .saq-question-body,
    StructuredAskUserWidget.is-submitted .saq-footer,
    StructuredAskUserWidget.is-submitted .saq-hint,
    StructuredAskUserWidget.is-submitted .saq-recap,
    StructuredAskUserWidget.is-submitted .saq-separator {
        display: none;
    }

    StructuredAskUserWidget.is-submitted .saq-answered-box {
        display: block;
    }

    StructuredAskUserWidget.is-submitted .saq-title {
        margin: 0;
    }

    StructuredAskUserWidget .saq-answered-row {
        height: auto;
        color: $text;
        padding: 0;
        margin: 0;
    }

    /* ── HITL: plan body rendering ─────────────────────────────────── */

    StructuredAskUserWidget .saq-body-box {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary 40%;
        background: $surface;
        overflow: hidden;
    }

    StructuredAskUserWidget .saq-body {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0;
        color: $text;
    }

    StructuredAskUserWidget .saq-body-path {
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
        color: $text-muted;
        text-style: italic;
    }

    /* ── HITL: comment input for Refine/Edit ───────────────────────── */

    StructuredAskUserWidget .saq-comment-row {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0 0 0 2;
    }

    StructuredAskUserWidget .saq-comment-input {
        margin: 0;
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $surface;
        border: none;
    }

    StructuredAskUserWidget .saq-comment-input:disabled {
        opacity: 0.5;
    }

    StructuredAskUserWidget .saq-comment-hint {
        height: auto;
        padding: 0;
        margin: 0 0 0 2;
        color: $text-muted;
        text-style: italic;
    }

    /* ── HITL: expand/collapse plan body in answered view ──────────── */

    StructuredAskUserWidget .saq-expand-toggle {
        height: auto;
        color: $primary;
        text-style: italic;
        padding: 0;
        margin: 0;
    }

    StructuredAskUserWidget.is-submitted .saq-body-box.is-expanded {
        display: block;
    }
    """

    class Submitted(Message):
        """Bubbles when the user submits answers or abandons."""

        def __init__(
            self,
            *,
            step_id: str,
            questions: list,
            answers: list[str],
            widget_id: str,
            origin_node: str = "",
        ) -> None:
            super().__init__()
            self.step_id = step_id
            self.questions = questions
            self.answers = answers
            self.widget_id = widget_id
            self.origin_node = origin_node

    def __init__(
        self,
        *,
        step_id: str,
        questions: list,
        widget_id: str | None = None,
        origin_node: str | None = None,
        degraded: bool = False,
        body_markdown: str | None = None,
        body_path: str | None = None,
        allow_custom: bool = True,
        comment_option_index: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._step_id = step_id
        self._questions = questions
        self._degraded = degraded
        self._origin_node = (origin_node or "").strip()
        self._widget_id = widget_id or self.id or ""
        self._current_q = 0
        self._selected: dict[int, int] = {}  # q_idx → option_idx (0–2) or 3 (custom)
        self._custom_texts: dict[int, str] = {}
        self._highlighted = 0  # 0–3 within current question (3 = custom)
        self._rendered_opt_count = 0  # option rows created at compose time
        self._submit_review_open = False
        self._submitted = False
        self._answers: list[str] = []
        self._degraded_inputs: list[Input] = []
        self._custom_input: Input | None = None
        self._submit_btn: Button | None = None
        self._abandon_btn: Button | None = None
        self._footer_focused = False  # False = question area, True = footer
        self._focus_guard_timer = None  # recurring timer that steals focus back from chat input
        # HITL extensions
        self._body_markdown = (body_markdown or "").strip()
        self._body_path = (body_path or "").strip()
        self._allow_custom = allow_custom
        self._comment_option_index = comment_option_index  # option idx that shows comment
        self._comment_input: Input | None = None
        self._comment_text: str = ""
        self._body_expanded = False
        self._plan_body_widget: Static | None = None
        self._plan_body_text: str = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _is_structured(self) -> bool:
        return not self._degraded

    @property
    def _is_hitl(self) -> bool:
        """True for plan-review and tool-approval origins."""
        return self._origin_node in _HITL_ORIGINS

    @property
    def _is_plan_review(self) -> bool:
        return self._origin_node == _ORIGIN_PLAN_MODE_REVIEW

    @property
    def _is_tool_approval(self) -> bool:
        return self._origin_node == _ORIGIN_TOOL_APPROVAL

    @property
    def _num_questions(self) -> int:
        return len(self._questions)

    @property
    def _all_answered(self) -> bool:
        return len(self._selected) >= self._num_questions

    def _question_header(self, idx: int) -> str:
        q = self._questions[idx]
        if isinstance(q, dict):
            return q.get("header", f"Q{idx + 1}")
        return str(q)

    def _question_question(self, idx: int) -> str:
        q = self._questions[idx]
        if isinstance(q, dict):
            return q.get("question", "")
        return str(q)

    def _question_options(self, idx: int) -> list[dict[str, str]]:
        """Return list of option dicts with 'label' and 'description' keys."""
        q = self._questions[idx]
        if isinstance(q, dict):
            return q.get("options", [])
        return []

    def _answer_text(self, q_idx: int) -> str:
        """The text to send on resume for the selected answer."""
        sel = self._selected.get(q_idx)
        if sel is None:
            return ""
        if not self._allow_custom and sel == 3:
            # HITL custom shouldn't happen, but guard.
            return ""
        if sel == 3:
            return self._custom_texts.get(q_idx, "")
        options = self._question_options(q_idx)
        if sel < len(options):
            return options[sel].get("label", "")
        return ""

    def _hitl_comment_label(self) -> str:
        """The comment text from the HITL comment input (if any)."""
        if self._comment_input is not None:
            return str(self._comment_input.value or "").strip()
        return self._comment_text

    def _answers_collected(self) -> list[str]:
        """All answer texts in question order (empty string if unanswered).

        For HITL origins, appends the comment text as a second slot when
        the Refine/Edit option is selected — the wire shape is
        ``[action, comment]`` for the host decoder.
        """
        answers = [self._answer_text(i) for i in range(self._num_questions)]
        if self._is_hitl and self._comment_option_index is not None:
            sel = self._selected.get(0)
            if sel == self._comment_option_index and self._hitl_comment_label():
                # Append comment as second answer for the host decoder.
                if len(answers) == 1:
                    answers.append(self._hitl_comment_label())
                elif len(answers) > 1:
                    answers[1] = self._hitl_comment_label()
        return answers

    # ------------------------------------------------------------------
    # Title content
    # ------------------------------------------------------------------

    def _title_content(self) -> Content:
        if self._is_plan_review:
            title = "Review this plan"
        elif self._is_tool_approval:
            title = self._tool_approval_title()
        elif self._submitted and self._answers:
            title = "Answered (from human)"
        else:
            title = "Awaiting your answer"
        if self._submitted:
            return _assemble_card_header(self, title, status="success")
        colors = theme.get_theme_colors(self)
        return _assemble_card_header(self, title, status="pending", accent=colors.warning)

    def _tool_approval_title(self) -> str:
        """Build the tool-approval card title from the first question.

        Each HITL question for tool_approval is shaped as a ``QuestionSpec``
        with ``header`` = ``"Approve <name> (<arg>)"``. The card title
        re-shapes it to ``"Approve tool: <name> (<arg>)"``. Multiple
        pending tool calls collapse into one title.
        """
        if not self._questions:
            return "Approve tool"
        q0 = self._questions[0]
        if isinstance(q0, dict):
            body = q0.get("header", "")
        else:
            body = str(q0)
        if body.startswith("Approve "):
            body = body[len("Approve ") :]
        if body.endswith("?"):
            body = body[:-1]
        more = len(self._questions) - 1
        if more > 0:
            return f"Approve {more + 1} tools: {body} (+{more} more)"
        return f"Approve tool: {body}"

    def _path_footer_text(self) -> str:
        if self._body_path:
            return f"Plan saved to: {self._body_path}"
        return "Plan held in memory only"

    def _refresh_title(self) -> None:
        try:
            title_w = self.query_one(".saq-title", Static)
            title_w.update(self._title_content())
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> Any:
        yield Static(self._title_content(), classes="saq-title", markup=False)
        # Answered summary — visible only when is-submitted (CSS toggles).
        yield from self._compose_answered_summary()
        if self._degraded:
            yield from self._compose_degraded()
        else:
            yield from self._compose_structured()

    def _compose_answered_summary(self) -> Any:
        gutter = _card_body_gutter()
        with Vertical(classes="saq-answered-box"):
            if self._is_hitl:
                # HITL answered view: action label + optional comments + body toggle
                answer = self._answers[0] if self._answers else ""
                comments = self._answers[1] if len(self._answers) > 1 else ""
                display_action = answer
                # Tool-approval "Approve" reads as past-tense "Approved"
                if self._is_tool_approval and answer == "Approve":
                    display_action = "Approved"
                shows_comments = comments and answer in ("Refine", "Edit")
                summary = f"{display_action}: {comments}" if shows_comments else display_action
                yield Static(
                    f"{gutter}[{summary}]",
                    classes="saq-answered-row",
                    markup=False,
                )
                if self._is_plan_review and self._body_markdown.strip():
                    g = get_glyphs()
                    yield Static(
                        f"{g.expand} Plan body — click or press Enter to expand",
                        classes="saq-expand-toggle",
                        markup=True,
                    )
            else:
                for i in range(self._num_questions):
                    yield Static(
                        f"{gutter}[{self._question_header(i)} → {self._answer_text(i) or '—'}]",
                        classes="saq-answered-row",
                        markup=False,
                    )

    def _compose_structured(self) -> Any:
        # Top visual separator — clearly distinguishes the QA widget from
        # surrounding messages in the transcript.
        yield Static("─" * 60, classes="saq-separator", markup=False)
        # HITL plan review: render the plan body above the options.
        if self._is_plan_review and self._body_markdown.strip():
            body = _strip_plan_frontmatter(self._body_markdown)
            with Vertical(classes="saq-body-box"):
                body_widget = Static("", classes="saq-body", markup=False)
                yield body_widget
                self._plan_body_widget = body_widget
                self._plan_body_text = body
            if self._body_path:
                yield Static(
                    self._path_footer_text(),
                    classes="saq-body-path",
                    markup=False,
                )
        # Tab bar (hidden for single question — CSS can't conditionally
        # hide, so we just don't render it when there's only one question).
        if self._num_questions > 1:
            with Horizontal(classes="saq-tab-bar"):
                for i in range(self._num_questions):
                    yield Static(
                        self._tab_label(i),
                        id=f"saq-tab-{i}",
                        classes="saq-tab",
                        markup=False,
                    )
        with Vertical(classes="saq-question-body"):
            yield Static(
                self._question_header(self._current_q),
                classes="saq-question-title",
                id="saq-qtitle",
                markup=False,
            )
            yield Static(
                self._question_question(self._current_q),
                classes="saq-description",
                id="saq-desc",
                markup=False,
            )
            with Vertical(classes="saq-option-list"):
                options = self._question_options(self._current_q)
                # Guard: if options are missing/malformed, fall back to a
                # free-text row so the user can still answer.  This covers
                # LLM outputs that pass the ``is_structured`` key-check but
                # carry empty or non-list options.
                _has_renderable_opts = isinstance(options, list) and len(options) > 0
                if not _has_renderable_opts:
                    logger.warning(
                        "StructuredAskUserWidget: question %r has no renderable "
                        "options (got %r). Falling back to free-text input.",
                        self._question_header(self._current_q),
                        options,
                    )
                # Rows rendered for the initial question; tab switches update
                # these in place (and hide extras when a question has fewer
                # options — see _update_question_display).
                self._rendered_opt_count = len(options) if _has_renderable_opts else 0
                for j, opt in enumerate(options if _has_renderable_opts else []):
                    label = opt.get("label", "") if isinstance(opt, dict) else ""
                    yield Static(
                        f"  {j + 1}. {label}",
                        id=f"saq-opt-{j}",
                        classes="saq-option-row",
                        markup=False,
                    )
                    # Long description directly below the label (muted).
                    desc = opt.get("description", "") if isinstance(opt, dict) else ""
                    yield Static(
                        f"     {desc}",
                        id=f"saq-optdesc-{j}",
                        classes="saq-option-desc",
                        markup=False,
                    )
                # "Other" custom row (implicit — auto-added, always last).
                # Suppressed for HITL origins (allow_custom=False).
                if self._allow_custom:
                    yield Static(
                        "  Other:",
                        id="saq-opt-custom",
                        classes="saq-option-row",
                        markup=False,
                    )
                    self._custom_input = Input(
                        placeholder="Type a custom answer…",
                        id="saq-custom-input",
                        classes="saq-custom-input",
                        disabled=_has_renderable_opts,
                    )
                    yield self._custom_input
                    # Auto-highlight the custom row when there are no options
                    # so the user can start typing immediately.
                    if not _has_renderable_opts:
                        self._highlighted = 0  # point at "Other"
                # HITL comment input: shown when the Refine/Edit option is selected.
                if self._is_hitl and self._comment_option_index is not None:
                    comment_placeholder = "Revised args…" if self._is_tool_approval else "Comments…"
                    self._comment_input = Input(
                        placeholder=comment_placeholder,
                        id="saq-comment-input",
                        classes="saq-comment-input",
                        disabled=True,
                    )
                    yield self._comment_input
            # Inline hint shown when custom row is highlighted but text is empty.
            if self._allow_custom:
                yield Static(
                    "Enter a custom answer or pick an option",
                    classes="saq-custom-hint",
                    id="saq-custom-hint",
                    markup=False,
                )
        # Recap (hidden until submit review opens)
        with Vertical(classes="saq-recap", id="saq-recap-box"):
            yield Static("Review:", classes="saq-recap-title", markup=False)
        # Footer
        with Horizontal(classes="saq-footer"):
            yield Static(
                f"{len(self._selected)}/{self._num_questions} answered",
                classes="saq-count",
                id="saq-count",
                markup=False,
            )
            yield Static(
                "Enter to submit",
                classes="saq-enter-hint",
                id="saq-enter-hint",
                markup=False,
            )
            self._submit_btn = Button(
                "Submit",
                id="saq-submit",
                variant="default",
                compact=True,
            )
            yield self._submit_btn
            self._abandon_btn = Button(
                "Abandon",
                id="saq-abandon",
                variant="default",
                compact=True,
            )
            yield self._abandon_btn
        # Bottom visual separator — mirrors the top rule.
        yield Static("─" * 60, classes="saq-separator", markup=False)

    def _compose_degraded(self) -> Any:
        for i, q in enumerate(self._questions):
            text = q if isinstance(q, str) else self._question_header(i)
            yield Static(
                f"Q{i + 1}: {text}",
                classes="saq-question-title",
                markup=False,
            )
            inp = Input(
                placeholder=f"Your answer for Q{i + 1}…",
                id=f"saq-degraded-input-{i}",
                classes="saq-degraded-input",
            )
            self._degraded_inputs.append(inp)
            yield inp
        yield Static(
            "Enter to submit · Esc to abandon",
            classes="saq-hint",
            markup=False,
        )
        with Horizontal(classes="saq-footer"):
            yield Static(
                f"{len(self._selected)}/{self._num_questions} answered",
                classes="saq-count",
                id="saq-count",
                markup=False,
            )
            self._submit_btn = Button(
                "Submit",
                id="saq-submit",
                variant="default",
                compact=True,
            )
            yield self._submit_btn
            self._abandon_btn = Button(
                "Abandon",
                id="saq-abandon",
                variant="default",
                compact=True,
            )
            yield self._abandon_btn

    def _tab_label(self, idx: int) -> str:
        """Label for a tab: ✓ if answered, ▸ if active, plus title."""
        g = get_glyphs()
        prefix = "▸ " if idx == self._current_q else "  "
        answered = idx in self._selected
        if answered:
            prefix = f"{g.checkmark} " if idx == self._current_q else f"{g.checkmark} "
        return f"{prefix}{self._question_header(idx)}"

    # ------------------------------------------------------------------
    # on_mount
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if self._submitted:
            self._refresh_answered_summary()
            return
        if self._degraded:
            if self._degraded_inputs:
                self._schedule_focus(self._degraded_inputs[0])
            return
        # Render plan body markdown for HITL plan review.
        if self._is_plan_review:
            self._render_plan_body()
        self._update_option_highlight()
        self._update_tab_highlight()
        self._update_submit_state()
        # Focus the widget so keybindings work.
        self._schedule_focus(self)
        # Belt-and-braces: keep focus pinned to the widget for the first
        # ~600 ms after mount so the user can immediately press ↑/↓/Enter
        # without the screen stealing focus back to the chat input.
        self._schedule_robust_focus()
        # Long-running focus guard: while the widget is active, anything
        # in the chat input that steals focus back to the prompt would
        # break arrow/Enter handling.  Poll every 200 ms and recapture
        # if focus has drifted to the chat input.  Stopped on submit/abandon.
        self._start_focus_guard()

    def _render_plan_body(self) -> None:
        """Render the plan body markdown via the themed renderer."""
        body_widget = self._plan_body_widget
        text = self._plan_body_text
        if body_widget is None:
            with suppress(Exception):
                body_widget = self.query_one(".saq-body", Static)
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

    def _start_focus_guard(self) -> None:
        """Begin a recurring timer that recaptures focus from the chat input.

        The TUI's chat input is the default focus target — the screen's
        post-mount layout, click handlers, and other lifecycle events all
        re-focus it. While the QA widget is waiting for an answer we
        need keyboard input to reach the widget, not the chat prompt.
        """

        def _tick() -> None:
            if self._submitted:
                return
            try:
                focused = self.app.focused
            except Exception:  # noqa: BLE001
                return
            # Only recapture if focus has drifted to the chat input.
            if not self._focus_is_on_chat(focused):
                return
            try:
                self.app.set_focus(self)
            except Exception:  # noqa: BLE001
                pass

        try:
            self._focus_guard_timer = self.set_interval(0.2, _tick)
        except Exception:  # noqa: BLE001
            self._focus_guard_timer = None

    def _stop_focus_guard(self) -> None:
        """Stop the focus-recapture timer (called on submit/abandon)."""
        timer = getattr(self, "_focus_guard_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:  # noqa: BLE001
                pass
            self._focus_guard_timer = None

    def _schedule_robust_focus(self) -> None:
        """Keep focus pinned to the widget for a brief window after mount.

        Textual's post-mount layout can move focus to the chat input or
        another child after `call_after_refresh` fires. Repeated
        focused attempts at increasing intervals ensure the widget
        retains keyboard navigation so arrow keys / Enter work
        immediately on appear.
        """

        def _refocus() -> None:
            try:
                if self._submitted:
                    return
                # Only recapture focus if something stole it from us.  The
                # chat input is the usual culprit (its post-mount
                # ``set_app_focus`` can re-focus the text area).  Skip
                # when another interactive widget already owns focus.
                focused = self.app.focused
                if focused is self:
                    return
                # If focus is on a descendant of ours, treat it as ours.
                if focused is not None:
                    try:
                        if self in focused.ancestors_with_self:
                            return
                    except Exception:  # noqa: BLE001
                        pass
                # Detect chat-input focus (covers the TextArea child too).
                if not self._focus_is_on_chat(focused):
                    return
            except Exception:  # noqa: BLE001
                pass
            try:
                self.app.set_focus(self)
            except Exception:  # noqa: BLE001
                pass

        try:
            self.set_timer(0.05, _refocus)
            self.set_timer(0.15, _refocus)
            self.set_timer(0.30, _refocus)
            self.set_timer(0.60, _refocus)
        except Exception:  # noqa: BLE001
            pass

    def _focus_is_on_chat(self, focused: Any) -> bool:
        """Return True if `focused` is the chat input (or its TextArea child)."""
        if focused is None:
            return False
        if focused.id == "chat-input":
            return True
        chat_input = getattr(self.app, "_chat_input", None)
        if chat_input is None:
            return False
        try:
            return focused in chat_input.walk_children()
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # HITL: plan body expand/collapse + comment focus guard
    # ------------------------------------------------------------------

    def _toggle_body_expanded(self) -> None:
        """Expand or collapse the plan body in the answered view."""
        self._body_expanded = not self._body_expanded
        try:
            body_box = self.query_one(".saq-body-box", Vertical)
            if self._body_expanded:
                body_box.add_class("is-expanded")
            else:
                body_box.remove_class("is-expanded")
        except Exception:  # noqa: BLE001
            pass
        self._refresh_answered_summary()

    def on_click(self, event: Click) -> None:
        """Toggle plan body expand/collapse in the answered (submitted) view."""
        if not self._is_plan_review or not self._submitted:
            return
        if screen_has_text_selection(self.screen):
            return
        event.stop()
        self._toggle_body_expanded()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        """Guard: the HITL comment input may only hold focus when the
        Refine/Edit option is the selected action."""
        if (
            self._comment_input is not None
            and event.widget is self._comment_input
            and self._comment_option_index is not None
        ):
            sel = self._selected.get(self._current_q)
            if sel != self._comment_option_index:
                self.screen.set_focus(self)

    # ------------------------------------------------------------------
    # Rendering updates
    # ------------------------------------------------------------------

    def _update_question_display(self) -> None:
        """Re-render the question body when switching tabs."""
        try:
            qtitle = self.query_one("#saq-qtitle", Static)
            qtitle.update(self._question_header(self._current_q))
        except Exception:  # noqa: BLE001
            pass
        try:
            desc = self.query_one("#saq-desc", Static)
            desc.update(self._question_question(self._current_q))
        except Exception:  # noqa: BLE001
            pass
        # Re-render option rows (labels + inline descriptions) in place.
        # Questions may have different option counts: extra rows from the
        # initially rendered question are hidden via the is-hidden class.
        options = self._question_options(self._current_q)
        num_opts = len(options)
        for j in range(self._rendered_opt_count):
            try:
                opt_w = self.query_one(f"#saq-opt-{j}", Static)
            except Exception:  # noqa: BLE001
                continue
            try:
                desc_w = self.query_one(f"#saq-optdesc-{j}", Static)
            except Exception:  # noqa: BLE001
                desc_w = None
            if j < num_opts:
                label = options[j].get("label", "") if isinstance(options[j], dict) else ""
                opt_w.update(f"  {j + 1}. {label}")
                opt_w.remove_class("is-hidden")
                if desc_w is not None:
                    opt_desc = (
                        options[j].get("description", "") if isinstance(options[j], dict) else ""
                    )
                    desc_w.update(f"     {opt_desc}")
                    desc_w.remove_class("is-hidden")
            else:
                opt_w.update("")
                opt_w.add_class("is-hidden")
                if desc_w is not None:
                    desc_w.update("")
                    desc_w.add_class("is-hidden")
        # Restore selection highlight for this question
        self._highlighted = self._selected.get(self._current_q, 0)
        self._update_option_highlight()
        self._update_tab_highlight()

    # Suffix appended to the selected option's label text so the user sees
    # an inline "Enter to submit." hint right next to their chosen answer.
    _SELECTED_HINT = "  ← Enter to submit."

    def _option_label(self, q_idx: int, opt_idx: int) -> str:
        """Build the display text for an option row (without hint)."""
        options = self._question_options(q_idx)
        if opt_idx < len(options):
            label = options[opt_idx].get("label", "") if isinstance(options[opt_idx], dict) else ""
            return f"  {opt_idx + 1}. {label}"
        return ""

    def _update_option_highlight(self) -> None:
        """Update which option row is highlighted."""
        num_opts = len(self._question_options(self._current_q))
        custom_idx = num_opts  # Custom row is always at index == num_opts
        for j in range(num_opts):
            try:
                opt_w = self.query_one(f"#saq-opt-{j}", Static)
                if j == self._highlighted:
                    opt_w.add_class("is-highlighted")
                    opt_w.remove_class("is-selected")
                else:
                    opt_w.remove_class("is-highlighted")
                    sel = self._selected.get(self._current_q)
                    if sel is not None and sel == j:
                        opt_w.add_class("is-selected")
                    else:
                        opt_w.remove_class("is-selected")
                # Append the inline hint to the selected option's text so the
                # user knows they can press Enter to submit their choice.
                base_text = self._option_label(self._current_q, j)
                sel = self._selected.get(self._current_q)
                if sel is not None and sel == j and j != self._highlighted:
                    opt_w.update(f"{base_text}{self._SELECTED_HINT}")
                else:
                    opt_w.update(base_text)
            except Exception:  # noqa: BLE001
                pass
        # Custom row (only when allow_custom)
        if self._allow_custom:
            try:
                custom_w = self.query_one("#saq-opt-custom", Static)
                if self._highlighted == custom_idx:
                    custom_w.add_class("is-highlighted")
                    custom_w.remove_class("is-selected")
                else:
                    custom_w.remove_class("is-highlighted")
                    sel = self._selected.get(self._current_q)
                    if sel is not None and sel == custom_idx:
                        custom_w.add_class("is-selected")
                    else:
                        custom_w.remove_class("is-selected")
                # Inline hint for a selected custom answer.
                sel = self._selected.get(self._current_q)
                custom_text = (
                    str(self._custom_input.value or "").strip()
                    if self._custom_input is not None
                    else ""
                )
                if (
                    sel is not None
                    and sel == custom_idx
                    and custom_idx != self._highlighted
                    and custom_text
                ):
                    custom_w.update(f"  Other: {custom_text}{self._SELECTED_HINT}")
                elif sel is not None and sel == custom_idx and custom_idx != self._highlighted:
                    custom_w.update(f"  Other:{self._SELECTED_HINT}")
                else:
                    custom_w.update("  Other:")
            except Exception:  # noqa: BLE001
                pass
        # Enable custom input only when custom row is highlighted
        if self._custom_input is not None:
            self._custom_input.disabled = self._highlighted != custom_idx
        # Show the custom-empty hint when the custom row is highlighted but
        # the input has no text (§9c.7).
        if self._allow_custom:
            try:
                hint = self.query_one("#saq-custom-hint", Static)
                custom_text = (
                    str(self._custom_input.value or "").strip()
                    if self._custom_input is not None
                    else ""
                )
                if self._highlighted == custom_idx and not custom_text:
                    hint.add_class("is-visible")
                else:
                    hint.remove_class("is-visible")
            except Exception:  # noqa: BLE001
                pass
        # HITL: enable/disable comment input based on the selected option.
        if self._comment_input is not None and self._comment_option_index is not None:
            sel = self._selected.get(self._current_q)
            should_enable = sel is not None and sel == self._comment_option_index
            self._comment_input.disabled = not should_enable

    def _update_tab_highlight(self) -> None:
        """Update tab labels to reflect current question and answered state."""
        if self._num_questions <= 1:
            return
        for i in range(self._num_questions):
            try:
                tab = self.query_one(f"#saq-tab-{i}", Static)
                tab.update(self._tab_label(i))
                if i == self._current_q:
                    tab.add_class("is-active")
                else:
                    tab.remove_class("is-active")
                if i in self._selected:
                    tab.add_class("is-answered")
                else:
                    tab.remove_class("is-answered")
            except Exception:  # noqa: BLE001
                pass

    def _update_submit_state(self) -> None:
        """Enable/disable Submit based on whether all questions are answered."""
        if self._submit_btn is not None:
            if self._all_answered:
                self._submit_btn.remove_class("is-disabled")
            else:
                self._submit_btn.add_class("is-disabled")
        # Update count
        try:
            count = self.query_one("#saq-count", Static)
            count.update(f"{len(self._selected)}/{self._num_questions} answered")
        except Exception:  # noqa: BLE001
            pass
        # Show the "Enter to submit" hint once every question is answered.
        try:
            hint = self.query_one("#saq-enter-hint", Static)
            if self._all_answered:
                hint.add_class("is-visible")
            else:
                hint.remove_class("is-visible")
        except Exception:  # noqa: BLE001
            pass

    def _refresh_answered_summary(self) -> None:
        """Update the collapsed answered view after submit."""
        try:
            box = self.query_one(".saq-answered-box", Vertical)
            # Clear and re-populate
            for child in list(box.children):
                child.remove()
            gutter = _card_body_gutter()
            if self._is_hitl:
                answers = self._answers if hasattr(self, "_answers") else self._answers_collected()
                action = answers[0] if answers else ""
                comments = answers[1] if len(answers) > 1 else ""
                display_action = action
                if self._is_tool_approval and action == "Approve":
                    display_action = "Approved"
                shows_comments = comments and action in ("Refine", "Edit")
                summary = f"{display_action}: {comments}" if shows_comments else display_action
                box.mount(
                    Static(
                        f"{gutter}[{summary}]",
                        classes="saq-answered-row",
                        markup=False,
                    )
                )
                if self._is_plan_review and self._body_markdown.strip():
                    g = get_glyphs()
                    toggle = Static(
                        f"{g.expand} Plan body — click or press Enter to expand"
                        if not self._body_expanded
                        else f"{g.collapse} Collapse plan body",
                        classes="saq-expand-toggle",
                        markup=True,
                    )
                    box.mount(toggle)
            else:
                for i in range(self._num_questions):
                    answer = self._answer_text(i)
                    label = answer if answer else "—"
                    box.mount(
                        Static(
                            f"{gutter}[{self._question_header(i)} → {label}]",
                            classes="saq-answered-row",
                            markup=False,
                        )
                    )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Submit recap
    # ------------------------------------------------------------------

    def _open_submit_review(self) -> None:
        """Render the recap block above the footer."""
        self._submit_review_open = True
        try:
            recap_box = self.query_one("#saq-recap-box", Vertical)
            # Clear title and populate rows
            for child in list(recap_box.children):
                child.remove()
            recap_box.mount(Static("Review:", classes="saq-recap-title", markup=False))
            for i in range(self._num_questions):
                answer = self._answer_text(i)
                label = answer if answer else "—"
                recap_box.mount(
                    Static(
                        f"  {self._question_header(i)} → {label}",
                        classes="saq-recap-row",
                        markup=False,
                    )
                )
            recap_box.add_class("is-visible")
        except Exception:  # noqa: BLE001
            pass

    def _close_submit_review(self) -> None:
        self._submit_review_open = False
        try:
            recap_box = self.query_one("#saq-recap-box", Vertical)
            for child in list(recap_box.children):
                child.remove()
            recap_box.mount(Static("Review:", classes="saq-recap-title", markup=False))
            recap_box.remove_class("is-visible")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    def _finalize(self) -> None:
        """Collect answers and post Submitted."""
        if self._submitted:
            return
        self._submitted = True
        self._stop_focus_guard()
        self.add_class("is-submitted")
        self._answers = self._answers_collected()
        self._refresh_title()
        self._refresh_answered_summary()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=self._questions,
                answers=self._answers,
                widget_id=self._widget_id,
                origin_node=self._origin_node,
            )
        )

    def _abandon(self) -> None:
        """Post Submitted with empty answers."""
        if self._submitted:
            return
        self._submitted = True
        self._stop_focus_guard()
        self.add_class("is-submitted")
        self._answers = []
        self._refresh_title()
        self._refresh_answered_summary()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=self._questions,
                answers=[],
                widget_id=self._widget_id,
                origin_node=self._origin_node,
            )
        )

    # ------------------------------------------------------------------
    # Keybinding actions
    # ------------------------------------------------------------------

    def action_prev_question(self) -> None:
        if self._degraded or self._submitted or self._submit_review_open:
            return
        if self._num_questions <= 1:
            return
        self._current_q = (self._current_q - 1) % self._num_questions
        self._update_question_display()

    def action_next_question(self) -> None:
        if self._degraded or self._submitted or self._submit_review_open:
            return
        if self._num_questions <= 1:
            return
        self._current_q = (self._current_q + 1) % self._num_questions
        self._update_question_display()

    def action_prev_option(self) -> None:
        if self._degraded or self._submitted or self._submit_review_open:
            return
        num_opts = len(self._question_options(self._current_q))
        total = num_opts + (1 if self._allow_custom else 0)
        self._highlighted = (self._highlighted - 1) % total
        self._update_option_highlight()

    def action_next_option(self) -> None:
        if self._degraded or self._submitted or self._submit_review_open:
            return
        num_opts = len(self._question_options(self._current_q))
        total = num_opts + (1 if self._allow_custom else 0)
        self._highlighted = (self._highlighted + 1) % total
        self._update_option_highlight()

    def action_confirm(self) -> None:
        """Enter: select highlighted option, or finalize submit review."""
        if self._submitted:
            # HITL plan review: toggle body expand after submit.
            if self._is_plan_review:
                self._toggle_body_expanded()
            return
        if self._submit_review_open:
            # Enter on the recap = submit
            self._finalize()
            return
        if self._degraded:
            return
        num_opts = len(self._question_options(self._current_q))
        custom_idx = num_opts  # Custom row is at index == num_opts (if allowed)
        if self._allow_custom and self._highlighted == custom_idx:
            # Custom row — focus the input if not yet selected
            if self._custom_input is not None and not self._custom_input.disabled:
                self._schedule_focus(self._custom_input)
            return
        # Select the highlighted option
        self._selected[self._current_q] = self._highlighted
        self._update_option_highlight()
        self._update_tab_highlight()
        self._update_submit_state()
        # HITL: if the selected option has a comment field, focus it.
        if (
            self._comment_option_index is not None
            and self._highlighted == self._comment_option_index
            and self._comment_input is not None
        ):
            self._schedule_focus(self._comment_input)
            return
        # HITL: immediate submit on action selection (Approve/Reject).
        if self._is_hitl:
            self._finalize()
            return
        # Auto-advance to next unanswered question; when every question is
        # answered, open the submit review so Enter finalizes.
        if not self._all_answered:
            for i in range(1, self._num_questions + 1):
                next_q = (self._current_q + i) % self._num_questions
                if next_q not in self._selected:
                    self._current_q = next_q
                    self._update_question_display()
                    break
        else:
            self._open_submit_review()
            self._schedule_focus(self)

    def action_abandon(self) -> None:
        if self._submitted:
            return
        if self._submit_review_open:
            # First Escape closes the review so answers stay editable;
            # a second Escape (outside review) abandons.
            self._close_submit_review()
            return
        self._abandon()

    def action_focus_footer(self) -> None:
        """Tab: cycle focus between Submit → Abandon → back to question area.

        In the submit-review state, Tab stays within the recap's Submit and
        Abandon buttons. In degraded mode, Tab cycles between the Submit
        button and the first input.
        """
        if self._submitted:
            return
        if self._submit_btn is None or self._abandon_btn is None:
            return
        if self._footer_focused:
            # Currently on footer — cycle to the other footer button, or
            # back to the question area if we've visited both.
            if self.app.focused is self._submit_btn:
                self._schedule_focus(self._abandon_btn)
            elif self.app.focused is self._abandon_btn:
                self._footer_focused = False
                self._schedule_focus(self)
            else:
                self._schedule_focus(self._submit_btn)
        else:
            self._footer_focused = True
            self._schedule_focus(self._submit_btn)

    # ------------------------------------------------------------------
    # Focus management
    # ------------------------------------------------------------------

    def _schedule_focus(self, widget: Any) -> None:
        app = self.app

        def _focus() -> None:
            try:
                app.set_focus(widget)
            except Exception:  # noqa: BLE001
                try:
                    widget.focus()
                except Exception:  # noqa: BLE001
                    logger.debug("StructuredAskUserWidget: focus failed", exc_info=True)

        try:
            self.call_after_refresh(_focus)
        except Exception:  # noqa: BLE001
            _focus()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if self._submitted:
            return
        btn_id = event.button.id or ""
        if btn_id == "saq-submit":
            event.stop()
            if self._degraded:
                self._finalize_degraded()
                return
            if self._all_answered:
                if self._submit_review_open:
                    self._finalize()
                else:
                    self._open_submit_review()
        elif btn_id == "saq-abandon":
            event.stop()
            self._abandon()

    @on(Input.Changed)
    def _on_input_changed(self, event: Input.Changed) -> None:
        """Update the custom-empty hint when the custom input text changes."""
        if event.input is self._custom_input:
            try:
                hint = self.query_one("#saq-custom-hint", Static)
                text = str(event.input.value or "").strip()
                if text:
                    hint.remove_class("is-visible")
                elif self._highlighted == 3:
                    hint.add_class("is-visible")
            except Exception:  # noqa: BLE001
                pass

    @on(Input.Submitted)
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if self._submitted:
            event.stop()
            return
        # HITL: comment input — Enter submits with the comment.
        if event.input is self._comment_input:
            event.stop()
            self._comment_text = str(event.input.value or "").strip()
            self._finalize()
            return
        if self._degraded:
            # In degraded mode, Enter on an input finalizes if all filled
            idx = -1
            for i, inp in enumerate(self._degraded_inputs):
                if event.input is inp:
                    idx = i
                    break
            if idx < 0:
                return
            event.stop()
            self._selected[idx] = 0
            self._custom_texts[idx] = str(event.input.value or "").strip()
            self._update_submit_state()
            # Move to next blank or finalize
            next_blank = next(
                (
                    j
                    for j, inp in enumerate(self._degraded_inputs)
                    if j != idx and not str(inp.value or "").strip()
                ),
                None,
            )
            if next_blank is not None:
                self._schedule_focus(self._degraded_inputs[next_blank])
            else:
                self._finalize()
            return
        # Structured mode: custom input
        if event.input is self._custom_input:
            text = str(event.input.value or "").strip()
            if text:
                self._selected[self._current_q] = 3
                self._custom_texts[self._current_q] = text
                self._update_option_highlight()
                self._update_tab_highlight()
                self._update_submit_state()
                # Auto-advance to the next unanswered question; when all
                # are answered, open the submit review so Enter finalizes.
                if not self._all_answered:
                    for i in range(1, self._num_questions + 1):
                        next_q = (self._current_q + i) % self._num_questions
                        if next_q not in self._selected:
                            self._current_q = next_q
                            self._update_question_display()
                            break
                else:
                    self._open_submit_review()
                self._schedule_focus(self)
            event.stop()

    def _finalize_degraded(self) -> None:
        """Collect answers from degraded inputs and finalize."""
        if self._submitted:
            return
        answers = []
        for i, inp in enumerate(self._degraded_inputs):
            val = str(inp.value or "").strip()
            answers.append(val)
        # Broadcast single non-empty answer to all questions
        non_empty = [a for a in answers if a]
        if len(non_empty) == 1 and len(answers) > 1:
            answers = non_empty * len(answers)
        if not any(answers):
            return
        self._submitted = True
        self._selected = {i: 0 for i in range(len(answers))}
        self._custom_texts = {i: answers[i] for i in range(len(answers))}
        self._answers = answers
        self.add_class("is-submitted")
        self._refresh_title()
        self._refresh_answered_summary()
        self.post_message(
            self.Submitted(
                step_id=self._step_id,
                questions=self._questions,
                answers=answers,
                widget_id=self._widget_id,
                origin_node=self._origin_node,
            )
        )
