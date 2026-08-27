"""Structured multi-question option-picker widget for ``ask_user`` (RFC-622 §9c).

Mounted when a structured ``ask_user`` clarification request arrives (generic
``execute`` origin). The LLM emits ``QuestionSpec`` objects with a question,
header, and 2-4 options (each with label + description). The recommended
option has "(Recommended)" in its label. The widget renders tabs for
multi-question navigation (←/→), hover-preview option selection (↑/↓ + Enter),
an implicit "Other" custom free-text row, and a persistent footer with
Submit/Abandon + inline recap before final submit.

HITL plan-review and tool-approval origins stay on ``ClarificationInputMessage``;
this widget is only for the generic (execute) render path. A degraded mode
handles in-flight plain-string questions from before the schema upgrade.
"""

from __future__ import annotations

import logging
from typing import Any

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, Input, Static

from soothe_cli.display import theme
from soothe_cli.settings import get_glyphs
from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _card_body_gutter,
)

logger = logging.getLogger(__name__)

# Wire origin constant (mirrors host ORIGIN_EXECUTE). CLI must not import
# soothe host packages.
_ORIGIN_EXECUTE = "execute"


class StructuredAskUserWidget(Vertical):
    """Structured multi-question option-picker for generic ``ask_user``.

    Two modes:
    - **Structured** (default): tabs + options + hover-preview + footer.
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
        color: $text-muted;
        padding: 0;
        margin: 0 0 1 0;
    }

    StructuredAskUserWidget .saq-option-row {
        height: auto;
        width: 1fr;
        padding: 0;
        margin: 0;
        color: $text-muted;
    }

    StructuredAskUserWidget .saq-option-row.is-highlighted {
        color: $text;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-option-row.is-selected {
        color: $success;
        text-style: bold;
    }

    StructuredAskUserWidget .saq-preview-box {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary 40%;
        background: $surface;
        color: $text-muted;
    }

    StructuredAskUserWidget .saq-preview-box.is-empty {
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
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary 30%;
        background: $surface;
        color: $text;
    }

    StructuredAskUserWidget .saq-recap-title {
        text-style: bold;
        margin: 0 0 1 0;
    }

    StructuredAskUserWidget .saq-recap-row {
        height: auto;
        padding: 0;
        margin: 0;
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
    StructuredAskUserWidget.is-submitted .saq-recap {
        display: none;
    }

    StructuredAskUserWidget.is-submitted .saq-answered-box {
        display: block;
    }

    StructuredAskUserWidget .saq-answered-row {
        height: auto;
        color: $text;
        padding: 0;
        margin: 0;
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
        self._submit_review_open = False
        self._submitted = False
        self._degraded_inputs: list[Input] = []
        self._custom_input: Input | None = None
        self._submit_btn: Button | None = None
        self._abandon_btn: Button | None = None
        self._footer_focused = False  # False = question area, True = footer

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _is_structured(self) -> bool:
        return not self._degraded

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
        return ""

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
        if sel == 3:
            return self._custom_texts.get(q_idx, "")
        options = self._question_options(q_idx)
        if sel < len(options):
            return options[sel].get("label", "")
        return ""

    def _answers_collected(self) -> list[str]:
        """All answer texts in question order (empty string if unanswered)."""
        return [self._answer_text(i) for i in range(self._num_questions)]

    # ------------------------------------------------------------------
    # Title content
    # ------------------------------------------------------------------

    def _title_content(self) -> Content:
        title = "Awaiting your answer"
        if self._submitted:
            return _assemble_card_header(self, title, status="success")
        colors = theme.get_theme_colors(self)
        return _assemble_card_header(self, title, status="pending", accent=colors.warning)

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
            for i in range(self._num_questions):
                yield Static(
                    f"{gutter}[{self._question_header(i)} → {self._answer_text(i) or '—'}]",
                    classes="saq-answered-row",
                    markup=False,
                )

    def _compose_structured(self) -> Any:
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
                for j, opt in enumerate(options):
                    label = opt.get("label", "")
                    yield Static(
                        f"  {j + 1}. {label}",
                        id=f"saq-opt-{j}",
                        classes="saq-option-row",
                        markup=False,
                    )
                # "Other" custom row (implicit — auto-added, always last)
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
                    disabled=True,
                )
                yield self._custom_input
            # Inline hint shown when custom row is highlighted but text is empty.
            yield Static(
                "Enter a custom answer or pick an option",
                classes="saq-custom-hint",
                id="saq-custom-hint",
                markup=False,
            )
            # Preview box for highlighted option's long desc
            yield Static(
                "",
                classes="saq-preview-box is-empty",
                id="saq-preview",
                markup=False,
            )
        yield Static(
            "←/→ questions  ↑/↓ options  Enter select  Tab footer",
            classes="saq-hint",
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
        self._update_option_highlight()
        self._update_preview()
        self._update_tab_highlight()
        self._update_submit_state()
        # Focus the widget so keybindings work.
        self._schedule_focus(self)

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
        # Re-render options
        options = self._question_options(self._current_q)
        num_opts = len(options)
        for j in range(num_opts):
            try:
                opt_w = self.query_one(f"#saq-opt-{j}", Static)
                label = options[j].get("label", "") if j < len(options) else ""
                opt_w.update(f"  {j + 1}. {label}")
            except Exception:  # noqa: BLE001
                pass
        # Restore selection highlight for this question
        self._highlighted = self._selected.get(self._current_q, 0)
        self._update_option_highlight()
        self._update_preview()
        self._update_tab_highlight()

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
            except Exception:  # noqa: BLE001
                pass
        # Custom row
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
        except Exception:  # noqa: BLE001
            pass
        # Enable custom input only when custom row is highlighted
        if self._custom_input is not None:
            self._custom_input.disabled = self._highlighted != custom_idx
        # Show the custom-empty hint when the custom row is highlighted but
        # the input has no text (§9c.7).
        try:
            hint = self.query_one("#saq-custom-hint", Static)
            custom_text = (
                str(self._custom_input.value or "").strip()
                if self._custom_input is not None
                else ""
            )
            if self._highlighted == 3 and not custom_text:
                hint.add_class("is-visible")
            else:
                hint.remove_class("is-visible")
        except Exception:  # noqa: BLE001
            pass

    def _update_preview(self) -> None:
        """Update the hover-preview box with the highlighted option's description."""
        try:
            preview = self.query_one("#saq-preview", Static)
            options = self._question_options(self._current_q)
            num_opts = len(options)
            if self._highlighted < num_opts:
                desc = options[self._highlighted].get("description", "")
                preview.update(desc)
                preview.remove_class("is-empty")
                return
            # Custom row — no preview
            preview.update("")
            preview.add_class("is-empty")
            preview.update("")
            preview.add_class("is-empty")
            preview.update("")
            preview.add_class("is-empty")
        except Exception:  # noqa: BLE001
            pass

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

    def _refresh_answered_summary(self) -> None:
        """Update the collapsed answered view after submit."""
        try:
            box = self.query_one(".saq-answered-box", Vertical)
            # Clear and re-populate
            for child in list(box.children):
                child.remove()
            gutter = _card_body_gutter()
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
        except Exception:  # noqa: BLE001
            pass

    def _close_submit_review(self) -> None:
        self._submit_review_open = False
        try:
            recap_box = self.query_one("#saq-recap-box", Vertical)
            for child in list(recap_box.children):
                child.remove()
            recap_box.mount(Static("Review:", classes="saq-recap-title", markup=False))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    def _finalize(self) -> None:
        """Collect answers and post Submitted."""
        if self._submitted:
            return
        answers = [self._answer_text(i) for i in range(self._num_questions)]
        self._submitted = True
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

    def _abandon(self) -> None:
        """Post Submitted with empty answers."""
        if self._submitted:
            return
        self._submitted = True
        self.add_class("is-submitted")
        self._refresh_title()
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
        total = num_opts + 1  # +1 for custom row
        self._highlighted = (self._highlighted - 1) % total
        self._update_option_highlight()
        self._update_preview()

    def action_next_option(self) -> None:
        if self._degraded or self._submitted or self._submit_review_open:
            return
        num_opts = len(self._question_options(self._current_q))
        total = num_opts + 1  # +1 for custom row
        self._highlighted = (self._highlighted + 1) % total
        self._update_option_highlight()
        self._update_preview()

    def action_confirm(self) -> None:
        """Enter: select highlighted option, or finalize submit review."""
        if self._submitted:
            return
        if self._submit_review_open:
            # Enter on the recap = submit
            self._finalize()
            return
        if self._degraded:
            return
        num_opts = len(self._question_options(self._current_q))
        if self._highlighted == num_opts:
            # Custom row — focus the input if not yet selected
            if self._custom_input is not None and not self._custom_input.disabled:
                self._schedule_focus(self._custom_input)
            return
        # Select the highlighted option
        self._selected[self._current_q] = self._highlighted
        self._update_option_highlight()
        self._update_tab_highlight()
        self._update_submit_state()
        # Auto-advance to next unanswered question
        if not self._all_answered:
            for i in range(1, self._num_questions + 1):
                next_q = (self._current_q + i) % self._num_questions
                if next_q not in self._selected:
                    self._current_q = next_q
                    self._update_question_display()
                    break

    def action_abandon(self) -> None:
        if self._submitted:
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
                # Auto-advance
                if not self._all_answered:
                    for i in range(1, self._num_questions + 1):
                        next_q = (self._current_q + i) % self._num_questions
                        if next_q not in self._selected:
                            self._current_q = next_q
                            self._update_question_display()
                            break
                else:
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
