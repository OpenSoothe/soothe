"""Cognition reason (plan) message widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui.config import is_ascii_mode
from soothe_cli.tui.widgets.messages._helpers import _assemble_card_header

if TYPE_CHECKING:
    from textual.app import ComposeResult


class CognitionReasonMessage(Vertical):
    """Single card for plan assessment and plan reasoning (keep/new suffix).

    Header uses the same cognition-colored label plus foreground body as ``CognitionStepMessage``.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    CognitionReasonMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    CognitionReasonMessage .cognition-plan-header {
        height: auto;
        margin: 0;
        color: $foreground;
    }

    CognitionReasonMessage .plan-section-line {
        height: auto;
        margin-left: 3;
        color: $text-muted;
    }

    CognitionReasonMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    def __init__(
        self,
        *,
        next_action: str,
        status: str,
        iteration: int,
        plan_action: str = "new",
        assessment_reasoning: str = "",
        plan_reasoning: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize a plan-reason card.

        Args:
            next_action: User-facing plan-generate line (RFC-604 / IG-329).
            status: Plan status (continue, replan, done).
            iteration: Agent-loop iteration index.
            plan_action: ``keep`` or ``new`` (execution strategy).
            assessment_reasoning: Phase-1 status justification from plan-assess.
            plan_reasoning: Legacy phase-2 strategy text (usually empty after IG-329).
            **kwargs: Passed to ``Vertical``.
        """
        super().__init__(**kwargs)
        self._next_action = next_action.strip()
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
        elif self._next_action:
            parts.append(self._next_action)
        if len(parts) == 2:
            first = parts[0]
            if not first.endswith((".", "!", "?")):
                first = f"{first}."
            body = f"{first} {parts[1]}"
        elif parts:
            body = parts[0]
        else:
            body = ""
        if self._plan_action in ("keep", "new") and body:
            body = f"{body} · {self._plan_action}"
        return _assemble_card_header(self, "", body)

    def compose(self) -> ComposeResult:
        yield Static(self._plan_header_content(), classes="cognition-plan-header")

    def on_mount(self) -> None:
        """Use ASCII border variant when configured."""
        if is_ascii_mode():
            colors = theme.get_theme_colors(self)
            self.styles.border = ("ascii", colors.primary)
