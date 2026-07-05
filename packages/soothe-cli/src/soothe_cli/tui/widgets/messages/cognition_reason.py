"""Cognition reason (plan) message widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

if TYPE_CHECKING:
    from textual.app import ComposeResult


class CognitionReasonMessage(Vertical):
    """Single card for plan assessment and plan reasoning.

    Header uses the same stateful dot prefix plus foreground body as ``CognitionStepMessage``.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionReasonMessage {
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
        background: transparent;
    }

    CognitionReasonMessage .cognition-plan-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }
    """

    def __init__(
        self,
        *,
        status: str,
        iteration: int,
        plan_action: str = "new",
        assessment_reasoning: str = "",
        plan_reasoning: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a plan-reason card.

        Args:
            status: Plan status (continue, replan, done).
            iteration: Agent-loop iteration index.
            plan_action: ``keep`` or ``new`` (internal execution strategy, not displayed).
            assessment_reasoning: Phase-1 status justification from plan-assess.
            plan_reasoning: Plan-generate ``reasoning`` shown in the cognition card.
            **kwargs: Passed to ``Vertical``.
        """
        super().__init__(**kwargs)
        self._status = status
        self._iteration = iteration
        self._plan_action = plan_action if plan_action in ("keep", "new") else ""
        self._assessment_reasoning = assessment_reasoning.strip()
        self._plan_reasoning = plan_reasoning.strip()

    def _plan_header_content(self) -> Content:
        parts: list[str] = []
        if self._assessment_reasoning:
            parts.append(self._assessment_reasoning)
        if self._plan_reasoning:
            parts.append(self._plan_reasoning)
        if len(parts) == 2:
            first = parts[0]
            if not first.endswith((".", "!", "?")):
                first = f"{first}."
            body = f"{first} {parts[1]}"
        elif parts:
            body = parts[0]
        else:
            body = ""
        return _assemble_card_header(self, body, status=self._status)

    def compose(self) -> ComposeResult:
        yield Static(self._plan_header_content(), classes="cognition-plan-header")
