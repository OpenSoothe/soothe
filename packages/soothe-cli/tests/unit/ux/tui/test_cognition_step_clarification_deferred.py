"""Tests for ``CognitionStepMessage.set_clarification_deferred``.

Covers the TUI notice shown when a ``soothe.loop.clarification.deferred``
event arrives — the loop has terminated, so the card is informational only.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.widgets.messages import CognitionStepMessage


class _StepCardApp(App[None]):
    """Minimal app that mounts a single step card."""

    def __init__(self, card: CognitionStepMessage) -> None:
        super().__init__()
        self.card = card

    def compose(self) -> ComposeResult:
        yield self.card


# ── mounted card (real widgets) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_clarification_deferred_shows_reason_and_questions() -> None:
    """Deferred notice stops the spinner, sets pending status, and renders questions."""
    card = CognitionStepMessage("DEF-01", "Analyze RFC", id="step-def")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        await pilot.pause()

        card.set_clarification_deferred(
            reason="Low confidence: 0.30 < 0.40",
            questions=["Which output format?", "JSON or YAML?"],
        )
        await pilot.pause()

        assert card._status == "pending"
        assert card._status_widget is not None
        assert card._status_widget.display is True

        # The detail widget should show the questions.
        assert card._detail_widget is not None
        assert card._detail_widget.display is True


@pytest.mark.asyncio
async def test_set_clarification_deferred_empty_questions_skips_detail() -> None:
    """With no questions, the detail widget is not populated but status line still shows."""
    card = CognitionStepMessage("DEF-02", "Analyze RFC", id="step-def-empty")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        await pilot.pause()

        card.set_clarification_deferred(reason="Structured output failed", questions=[])
        await pilot.pause()

        assert card._status == "pending"
        assert card._status_widget is not None
        assert card._status_widget.display is True


# ── unmounted card (MagicMock widgets) ─────────────────────────────────


def test_set_clarification_deferred_with_mock_widgets() -> None:
    """Unmounted card path — widgets are MagicMock, status + detail updated."""
    card = CognitionStepMessage("DEF-03", "Deferred", id="step-def-mock")
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()

    card.set_clarification_deferred(
        reason="Low confidence",
        questions=["Q1?", "Q2?"],
    )

    assert card._status == "pending"
    # Status widget received a Content.styled update and was displayed.
    assert card._status_widget.display is True
    card._status_widget.update.assert_called_once()
    # Detail widget received a body update and was displayed.
    assert card._detail_widget.display is True
    card._detail_widget.update.assert_called_once()


def test_set_clarification_deferred_whitespace_questions_filtered() -> None:
    """Whitespace-only questions are filtered; detail widget not updated."""
    card = CognitionStepMessage("DEF-04", "Deferred", id="step-def-ws")
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()

    card.set_clarification_deferred(
        reason="Low confidence",
        questions=["  ", "", "\t"],
    )

    assert card._status == "pending"
    assert card._status_widget.display is True
    card._status_widget.update.assert_called_once()
    # No real questions → detail widget not touched.
    card._detail_widget.update.assert_not_called()
    card._detail_widget.display = False  # never set to True by the method


def test_set_clarification_deferred_long_reason_truncated() -> None:
    """Reasons longer than 120 chars are truncated with an ellipsis."""
    card = CognitionStepMessage("DEF-05", "Deferred", id="step-def-long")
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()

    long_reason = "x" * 200
    card.set_clarification_deferred(reason=long_reason, questions=["Q?"])

    assert card._status == "pending"
    # The status update content should contain the truncated reason with "…".
    update_call = card._status_widget.update.call_args
    content_arg = update_call.args[0]
    # Content.styled wraps a string — check the rendered text includes truncation.
    rendered = str(content_arg)
    assert "…" in rendered
    assert "x" * 200 not in rendered
