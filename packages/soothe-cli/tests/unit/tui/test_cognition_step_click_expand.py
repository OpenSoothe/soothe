"""Regression tests for CognitionStepMessage click-to-expand behavior."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.widgets.messages import CognitionStepMessage


class _StepCardHarnessApp(App[None]):
    """Minimal app that mounts a single step card."""

    def __init__(self) -> None:
        super().__init__()
        self.card = CognitionStepMessage("ASK-01", "Clarify requirements", id="step-card")

    def compose(self) -> ComposeResult:
        yield self.card


@pytest.mark.asyncio
async def test_click_expands_auto_collapsed_card_with_clarification() -> None:
    """Auto-collapsed terminal cards expand on first click to reveal detail."""
    async with _StepCardHarnessApp().run_test() as pilot:
        card = pilot.app.card
        for i in range(5):
            card.add_tool_call(f"ASK_01:s:grep:{i}", "grep", {"pattern": f"q{i}"})
            card.set_tool_success(f"ASK_01:s:grep:{i}", "ok", duration_ms=10)
        card.set_running()
        card.set_complete(True, 800, 5, "Done")
        await pilot.pause()

        # set_complete auto-collapses to title + status only.
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False

        # Clarification Q&A content is set but stays hidden while collapsed.
        card.set_clarification_details(
            questions=["What output format do you want?"],
            answers=["Markdown table"],
            source="human",
            confidence=None,
        )
        await pilot.pause()
        assert card._detail_widget.display is False

        # Clicking expands the card and reveals the clarification detail.
        await pilot.click("#step-card")
        await pilot.pause()

        assert not card.has_class("-collapsed")
        assert card._detail_widget.display is True
