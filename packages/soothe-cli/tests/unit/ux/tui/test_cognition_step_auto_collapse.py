"""Tests for auto-collapse of step and subagent cards on terminal status."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.widgets.messages import CognitionStepMessage
from soothe_cli.tui.widgets.messages.cognition_step import create_subagent_card


class _StepCardApp(App[None]):
    """Minimal app that mounts a single step card."""

    def __init__(self, card: CognitionStepMessage) -> None:
        super().__init__()
        self.card = card

    def compose(self) -> ComposeResult:
        yield self.card


# ── set_complete auto-collapse ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_complete_success_auto_collapses_card() -> None:
    """Completed step cards auto-collapse to title + status only."""
    card = CognitionStepMessage("S-01", "Run analysis", id="step-ok")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 1500, 3, "Done")
        await pilot.pause()

        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        # Status footer must stay visible.
        assert card._status_widget is not None
        assert card._status_widget.display is True


@pytest.mark.asyncio
async def test_set_complete_failed_auto_collapses_card() -> None:
    """Failed step cards auto-collapse to title + status only."""
    card = CognitionStepMessage("S-02", "Broken step", id="step-fail")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(False, 2000, 1, "Crashed")
        await pilot.pause()

        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        assert card._status_widget is not None
        assert card._status_widget.display is True


# ── set_interrupted auto-collapse ───────────────────────────────────────


@pytest.mark.asyncio
async def test_set_interrupted_auto_collapses_card() -> None:
    """Interrupted step cards auto-collapse, preserving the interrupt message."""
    card = CognitionStepMessage("S-03", "Running step", id="step-int")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_interrupted("Connection lost")
        await pilot.pause()

        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        # Status widget keeps the interrupt message (not overridden).
        assert card._status_widget is not None
        assert card._status_widget.display is True
        assert card._interrupt_message == "Connection lost"


@pytest.mark.asyncio
async def test_set_interrupted_empty_message_auto_collapses() -> None:
    """Interrupted with empty message still auto-collapses; status hidden."""
    card = CognitionStepMessage("S-04", "Silent cancel", id="step-silent")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_interrupted("")
        await pilot.pause()

        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False


# ── click to expand ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_click_expands_auto_collapsed_card() -> None:
    """Clicking an auto-collapsed card expands it and shows detail."""
    card = CognitionStepMessage("S-05", "Execute step", id="step-expand")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        # Provide execute prose so the detail has content when expanded.
        card.append_execute_assistant_delta("Working on it...")
        card.set_complete(True, 500, 2, "Done")
        await pilot.pause()

        assert card.has_class("-collapsed")

        await pilot.click("#step-expand")
        await pilot.pause()

        assert not card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is True


# ── clarification details respect collapse ─────────────────────────────


@pytest.mark.asyncio
async def test_set_clarification_details_respects_collapse() -> None:
    """Clarification Q&A content is set but stays hidden when auto-collapsed."""
    card = CognitionStepMessage("S-06", "Ask user", id="step-clar")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 300, 0, "Awaiting answer")
        await pilot.pause()

        assert card.has_class("-collapsed")

        card.set_clarification_details(
            questions=["Which format?"],
            answers=["JSON"],
            source="human",
            confidence=0.9,
        )
        await pilot.pause()

        # Content is on the widget but display stays False while collapsed.
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        assert card._has_clarification_details is True

        # Expanding reveals the clarification content.
        card.toggle_collapse()
        await pilot.pause()
        assert card._detail_widget.display is True


# ── result preview respects collapse ────────────────────────────────────


@pytest.mark.asyncio
async def test_set_result_preview_respects_collapse() -> None:
    """Result preview content is set but stays hidden when auto-collapsed."""
    card = CognitionStepMessage("S-07", "Goal completion", id="step-preview")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 1000, 0, "Completed")
        await pilot.pause()

        assert card.has_class("-collapsed")

        card.set_result_preview("Result line 1\nResult line 2")
        await pilot.pause()

        assert card._has_result_preview is True
        assert card._detail_widget is not None
        assert card._detail_widget.display is False

        # Expanding reveals the result preview.
        card.toggle_collapse()
        await pilot.pause()
        assert card._detail_widget.display is True


# ── subagent card auto-collapse ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_subagent_card_auto_collapses_on_complete() -> None:
    """SubAgent (orphan) cards auto-collapse on terminal status."""
    card = create_subagent_card(
        step_id="SUB-01",
        description="Deep research topic",
        subagent_type="deep_research",
        task_idx=0,
        id="subagent-card",
    )
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 5000, 4, "Researched")
        await pilot.pause()

        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False
        assert card._status_widget is not None
        assert card._status_widget.display is True


# ── manual collapse not overridden ─────────────────────────────────────


@pytest.mark.asyncio
async def test_manual_collapse_not_overridden_by_auto_collapse() -> None:
    """If the user manually collapsed before completion, auto-collapse is a no-op."""
    card = CognitionStepMessage("S-08", "Pre-collapsed", id="step-precol")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.toggle_collapse()  # manual collapse while running
        await pilot.pause()
        assert card._card_collapsed is True

        card.set_complete(True, 800, 2, "Done")
        await pilot.pause()

        # Still collapsed (auto-collapse didn't double-toggle).
        assert card._card_collapsed is True
        assert card.has_class("-collapsed")


# ── unmounted card (deferred path) ─────────────────────────────────────


def test_set_complete_deferred_does_not_auto_collapse() -> None:
    """Unmounted cards take the deferred path; auto-collapse runs on mount."""
    card = CognitionStepMessage("S-09", "Deferred", id="step-deferred")
    # _status_widget / _detail_widget are None → deferred path.
    card.set_complete(True, 1000, 1, "Done")
    assert card._status == "success"
    assert card._card_collapsed is False  # not collapsed yet (deferred)
    assert card._deferred_complete is not None


def test_set_complete_with_mock_widgets_auto_collapses() -> None:
    """Mounted-path with MagicMock widgets still sets collapse flag."""
    card = CognitionStepMessage("S-10", "Mocked", id="step-mock")
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()
    card.set_complete(True, 500, 2, "Done")
    # Auto-collapse sets flag and hides detail (display=False on mock).
    assert card._card_collapsed is True
    assert card._detail_widget.display is False


# ── surface sync after collapse ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_surface_sync_after_complete_does_not_re_expand() -> None:
    """A deferred tools refresh (or any _sync_step_card_surface call) after
    set_complete must not re-show body widgets on an auto-collapsed card."""
    card = CognitionStepMessage("S-11", "Tool-heavy step", id="step-sync")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 2000, 5, "Done")
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._detail_widget is not None
        assert card._detail_widget.display is False

        # Simulate a late surface sync (e.g. deferred tools refresh timer).
        card._sync_step_card_surface()
        await pilot.pause()

        # Card must still be collapsed — body widgets stay hidden.
        assert card.has_class("-collapsed")
        assert card._card_collapsed is True
        assert card._detail_widget.display is False
        if card._tools_widget is not None:
            assert card._tools_widget.display is False
        if card._activity_widget is not None:
            assert card._activity_widget.display is False


@pytest.mark.asyncio
async def test_expand_restores_body_widgets() -> None:
    """Expanding an auto-collapsed card re-syncs tools and activity visibility."""
    card = CognitionStepMessage("S-12", "Expand restore", id="step-restore")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 800, 2, "Done")
        await pilot.pause()
        assert card.has_class("-collapsed")

        card.toggle_collapse()  # expand
        await pilot.pause()

        assert not card.has_class("-collapsed")
        assert card._detail_widget is not None
        # Detail should be visible (no prose, no clarification, no preview → False).
        # The key assertion is that body widgets are managed correctly after expand.
        # Re-collapse should hide body widgets again.
        card.toggle_collapse()
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._detail_widget.display is False


# ── click to collapse expanded terminal card ────────────────────────────


@pytest.mark.asyncio
async def test_click_collapses_expanded_terminal_card() -> None:
    """Clicking an expanded terminal card collapses it back to title + status."""
    card = CognitionStepMessage("S-13", "Click collapse", id="step-clickcol")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(True, 500, 3, "Done")
        await pilot.pause()
        assert card.has_class("-collapsed")

        # First click expands.
        await pilot.click("#step-clickcol")
        await pilot.pause()
        assert not card.has_class("-collapsed")

        # Second click collapses.
        await pilot.click("#step-clickcol")
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._card_collapsed is True
        assert card._detail_widget is not None
        assert card._detail_widget.display is False


@pytest.mark.asyncio
async def test_click_collapses_expanded_failed_card() -> None:
    """Clicking an expanded failed card collapses it back."""
    card = CognitionStepMessage("S-14", "Failed step", id="step-clickfail")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.set_complete(False, 800, 1, "Error occurred")
        await pilot.pause()
        assert card.has_class("-collapsed")

        # Expand.
        await pilot.click("#step-clickfail")
        await pilot.pause()
        assert not card.has_class("-collapsed")

        # Collapse via click.
        await pilot.click("#step-clickfail")
        await pilot.pause()
        assert card.has_class("-collapsed")
