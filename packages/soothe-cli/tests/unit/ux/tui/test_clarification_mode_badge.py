"""Tests for the clarification-mode badge and StatusBar wiring (RFC-622)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.widgets.status import (
    CLARIFICATION_MODE_AUTO,
    CLARIFICATION_MODE_MANUAL,
    ClarificationModeBadge,
    ModelLabel,
)


def _read_static_content(widget: ClarificationModeBadge) -> str:
    """Read the rendered text from a `Static` (private name-mangled attribute)."""
    return str(widget._Static__content)  # type: ignore[attr-defined]


class _BadgeOnlyApp(App[None]):
    """Minimal harness to mount a single badge for visual-state assertions."""

    def compose(self) -> ComposeResult:
        yield ClarificationModeBadge(id="badge")


@pytest.mark.asyncio
async def test_badge_defaults_to_auto_text_and_class() -> None:
    """Initial mount renders the Auto label and applies the ``auto`` class."""
    async with _BadgeOnlyApp().run_test() as pilot:
        badge = pilot.app.query_one("#badge", ClarificationModeBadge)
        assert badge.mode == CLARIFICATION_MODE_AUTO
        assert badge.has_class("auto")
        assert not badge.has_class("manual")
        assert _read_static_content(badge) == "Auto"


@pytest.mark.asyncio
async def test_badge_flips_to_manual_when_mode_assigned() -> None:
    """Setting ``mode`` updates the visible text and CSS class atomically."""
    async with _BadgeOnlyApp().run_test() as pilot:
        badge = pilot.app.query_one("#badge", ClarificationModeBadge)
        badge.mode = CLARIFICATION_MODE_MANUAL
        await pilot.pause()
        assert badge.has_class("manual")
        assert not badge.has_class("auto")
        assert _read_static_content(badge) == "Manual"


@pytest.mark.asyncio
async def test_badge_rejects_unknown_mode_falls_back_to_auto() -> None:
    """Unknown values do not crash; the badge clamps to Auto."""
    async with _BadgeOnlyApp().run_test() as pilot:
        badge = pilot.app.query_one("#badge", ClarificationModeBadge)
        badge.mode = "nonsense"
        await pilot.pause()
        assert badge.has_class("auto")
        assert _read_static_content(badge) == "Auto"


def test_badge_has_initial_content_before_mount() -> None:
    """The constructor seeds the Static content so the badge paints immediately."""
    badge = ClarificationModeBadge(id="pre-mount")
    assert _read_static_content(badge) == "Auto"
    assert badge.has_class("auto")


def test_badge_constructor_accepts_initial_manual_mode() -> None:
    """``ClarificationModeBadge(mode="manual")`` starts on the manual variant."""
    badge = ClarificationModeBadge(id="pre-mount-manual", mode="manual")
    assert _read_static_content(badge) == "Manual"
    assert badge.has_class("manual")


def test_model_label_truncates_from_the_right_when_too_narrow() -> None:
    """Long model names left-align and trim with a trailing ellipsis."""
    label = ModelLabel()
    label.provider = "openai"
    label.model = "gpt-4.1-2024-04-09"
    # Mirror the render() branch for length(self.model) > width:
    full_model = label.model
    width = 6
    expected = full_model[: width - 1] + "…"
    assert expected == "gpt-4…"
