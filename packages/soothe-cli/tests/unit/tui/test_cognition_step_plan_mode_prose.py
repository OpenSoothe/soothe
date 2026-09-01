"""Plan-mode step card suppresses execute prose (plan markdown) on completion.

In plan mode, the agent's final message IS the plan document. The plan review
card (``StructuredAskUserWidget`` with origin ``plan_mode_review``) already
renders the full plan body (formatted, collapsible). Showing the raw plan
markdown again on the step card is redundant — especially after a refinement,
where the old step card would display the *original* plan alongside the
*refined* plan review card.

These tests verify that the step card's detail panel does NOT render the
execute prose when ``interaction_mode == "plan"``, while still preserving
the prose for dedup (``last_completed_execute_prose`` property).
"""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_plan_mode_suppresses_execute_prose_on_complete() -> None:
    """Completed plan-mode step cards do not render plan markdown in detail."""
    card = CognitionStepMessage(
        "S-PLAN-01",
        "Draft plan",
        interaction_mode="plan",
        id="step-plan-suppress",
    )
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        # Stream the plan markdown as execute-step prose.
        card.append_execute_assistant_delta("## Plan: Do the thing\n\n1. Step one\n")
        card.set_complete(True, 2000, 2, "Plan ready")
        await pilot.pause()

        # Card auto-collapses; detail is hidden.
        assert card._card_collapsed is True
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        # Detail widget content was cleared (no stale plan markdown).
        assert str(getattr(card._detail_widget, "_Static__content", "")).strip() == ""

        # Prose is still preserved for dedup.
        assert card.last_completed_execute_prose != ""
        assert "## Plan: Do the thing" in card.last_completed_execute_prose


@pytest.mark.asyncio
async def test_plan_mode_suppresses_prose_when_expanded() -> None:
    """Expanding a completed plan-mode step card does not show plan markdown."""
    card = CognitionStepMessage(
        "S-PLAN-02",
        "Draft plan",
        interaction_mode="plan",
        id="step-plan-expand",
    )
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.append_execute_assistant_delta("## Plan: Refined\n\nNew approach.\n")
        card.set_complete(True, 1000, 1, "Done")
        await pilot.pause()

        assert card._card_collapsed is True

        # Expand the card — detail should NOT show the plan prose.
        card.toggle_collapse()
        await pilot.pause()

        assert not card._card_collapsed
        assert card._detail_widget is not None
        # No clarification details or result preview → detail hidden.
        assert card._detail_widget.display is False


@pytest.mark.asyncio
async def test_agent_mode_shows_execute_prose_on_complete() -> None:
    """Non-plan (agent) mode step cards still render execute prose in detail."""
    card = CognitionStepMessage(
        "S-AGENT-01",
        "Execute task",
        interaction_mode=None,
        id="step-agent-prose",
    )
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.append_execute_assistant_delta("Here is the result of the task.")
        card.set_complete(True, 500, 0, "Done")
        await pilot.pause()

        assert card._card_collapsed is True

        # Expand — detail should show the execute prose.
        card.toggle_collapse()
        await pilot.pause()

        assert not card._card_collapsed
        assert card._detail_widget is not None
        assert card._detail_widget.display is True
        assert "Here is the result of the task." in str(
            getattr(card._detail_widget, "_Static__content", "")
        )


@pytest.mark.asyncio
async def test_plan_mode_suppress_property() -> None:
    """``_suppress_execute_prose`` is True only for plan mode."""
    plan_card = CognitionStepMessage("P", "p", interaction_mode="plan")
    ask_card = CognitionStepMessage("A", "a", interaction_mode="ask")
    agent_card = CognitionStepMessage("G", "g", interaction_mode=None)

    assert plan_card._suppress_execute_prose is True
    assert ask_card._suppress_execute_prose is False
    assert agent_card._suppress_execute_prose is False
