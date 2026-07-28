"""Clarification input message widget."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from textual import on
from textual.containers import Vertical
from textual.content import Content
from textual.message import Message
from textual.widgets import Input, Static

from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

logger = logging.getLogger(__name__)

# Wire origin id for planner-subagent review (mirrors host ORIGIN_PLANNER_SUBAGENT_REVIEW).
# CLI must not import soothe host packages; keep the wire string local.
_ORIGIN_PLANNER_SUBAGENT_REVIEW = "planner_subagent_review"


class ClarificationInputMessage(Vertical):
    """Inline answer-collection widget for a pending ``ask_user`` step (RFC-622).

    Mounted when ``soothe.loop.clarification.requested`` arrives. Shows the
    questions and one ``Input`` per question; on submit posts a
    :class:`ClarificationInputMessage.Submitted` message bubbling up to the
    app, which renders the answers on the matching step card and forwards
    them to the daemon as a ``loop_input`` with ``clarification_answer=True``.
    The widget marks itself completed (read-only) after submit so the user
    can still see what they answered without being able to re-edit.
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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._step_id = step_id
        self._questions: list[str] = [q for q in questions if q.strip()]
        self._origin_node = (origin_node or "").strip()
        self._inputs: list[Input] = []
        self._submitted = False
        self._answers: list[str] = []
        self._widget_id = widget_id or self.id or ""

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

    def compose(self) -> Any:
        yield Static(self._title_content(), classes="clarification-title")
        for i, q in enumerate(self._questions):
            q_classes = "clarification-question"
            if i > 0:
                q_classes += " has-separator"
            yield Static(f"Q{i + 1}: {q}", classes=q_classes, markup=False)
            placeholder = f"Your answer for Q{i + 1}…"
            if self._is_planner_subagent_review:
                if i == 0:
                    placeholder = "Approve / Reject / More comments…"
                else:
                    placeholder = "Optional comments (required for More comments)…"
            inp = Input(placeholder=placeholder, id=f"clarification-input-{i}")
            self._inputs.append(inp)
            yield inp

    def on_mount(self) -> None:
        if not self._inputs:
            return
        app = self.app
        if hasattr(app, "focus_primary_input"):
            app.focus_primary_input()
            return
        first_input = self._inputs[0]

        def _focus_first() -> None:
            try:
                app.set_focus(first_input)
            except Exception:  # noqa: BLE001
                try:
                    first_input.focus()
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "ClarificationInputMessage: failed to focus first input",
                        exc_info=True,
                    )

        try:
            self.call_after_refresh(_focus_first)
        except Exception:  # noqa: BLE001
            _focus_first()
        with suppress(Exception):
            self.set_timer(0.05, _focus_first)

    @on(Input.Submitted)
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if self._submitted:
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
