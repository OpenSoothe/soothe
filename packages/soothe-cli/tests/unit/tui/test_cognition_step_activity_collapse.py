"""Tests for activity-body collapse behavior in real Textual apps.

These tests reproduce the bug where completed cards with activity body
(tool calls, todos, subagent notes) don't collapse because
``_refresh_collapse_state`` only hides the detail widget via inline
``display = False`` — the activity widget retains its inline
``display = True`` from running, which Textual's inline-styles-priority
system does not let CSS ``display: none`` override.
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
async def test_auto_collapse_hides_activity_widget_with_tools() -> None:
    """Auto-collapse must hide the activity widget when it has tool calls."""
    card = CognitionStepMessage("S-01", "Tool step", id="step-act1")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        # Add a tool call so has_task_activity_body() returns True.
        card.add_tool_call("tc-1", "bash", {"command": "echo hello"})
        await pilot.pause()
        # Activity widget should be visible during running.
        assert card._activity_widget is not None
        assert card._activity_widget.display is True

        card.set_complete(True, 1000, 1, "Done")
        await pilot.pause()

        # After auto-collapse, activity widget must be hidden via inline style.
        assert card._card_collapsed is True
        assert card.has_class("-collapsed")
        assert card._activity_widget.display is False, (
            "Activity widget not hidden after auto-collapse — "
            "inline display=True from running not overridden"
        )


@pytest.mark.asyncio
async def test_click_collapse_hides_activity_widget_after_expand() -> None:
    """Clicking to collapse an expanded terminal card must hide activity widget.

    This is the core bug: _refresh_collapse_state collapsed branch only sets
    _detail_widget.display=False, leaving _activity_widget with its inline
    display=True from the expand phase.
    """
    card = CognitionStepMessage("S-02", "Click collapse", id="step-act2")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        card.add_tool_call("tc-2", "bash", {"command": "ls"})
        await pilot.pause()
        assert card._activity_widget is not None
        assert card._activity_widget.display is True

        card.set_complete(True, 500, 1, "Done")
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._activity_widget.display is False

        # Expand via click.
        await pilot.click("#step-act2")
        await pilot.pause()
        assert not card.has_class("-collapsed")
        # Activity widget should be visible after expand.
        assert card._activity_widget.display is True

        # Collapse via click — this is where the bug manifests.
        await pilot.click("#step-act2")
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._card_collapsed is True
        # Activity widget MUST be hidden — not just via CSS but via inline.
        assert card._activity_widget.display is False, (
            "Activity widget not hidden after click-collapse — "
            "_refresh_collapse_state must set display=False on activity widget"
        )


@pytest.mark.asyncio
async def test_toggle_collapse_hides_activity_widget_with_todos() -> None:
    """Toggle collapse on a card with todos must hide activity widget."""
    card = CognitionStepMessage("S-03", "Todo step", id="step-act3")
    async with _StepCardApp(card).run_test() as pilot:
        card.set_running()
        # Add todos so has_task_activity_body() returns True.
        card.set_todos([{"content": "Task 1", "status": "pending"}])
        await pilot.pause()
        assert card._activity_widget is not None
        assert card._activity_widget.display is True

        card.set_complete(True, 800, 0, "Done")
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._activity_widget.display is False

        # Expand and then collapse via toggle.
        card.toggle_collapse()  # expand
        await pilot.pause()
        assert card._activity_widget.display is True

        card.toggle_collapse()  # collapse
        await pilot.pause()
        assert card.has_class("-collapsed")
        assert card._activity_widget.display is False, (
            "Activity widget not hidden after toggle-collapse"
        )
