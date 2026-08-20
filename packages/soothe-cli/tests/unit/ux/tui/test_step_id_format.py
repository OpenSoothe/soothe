"""Tests for step id display formatting in the plan panel."""

from __future__ import annotations

import pytest

from soothe_cli.runtime.presentation.step_id_format import (
    display_step_id,
    numeric_step_prefix,
)


@pytest.mark.parametrize(
    ("step_id", "expected"),
    [
        # Canonical execute step ids: hyphen prefix + numeric suffix
        ("KFA-07", "7"),
        ("GHT-01", "1"),
        ("STEP-1", "1"),
        ("STEP-12", "12"),
        ("S-01", "1"),
        # Pure numeric fallback (no hyphen)
        ("01", "1"),
        ("1", "1"),
        ("0042", "42"),
        # Underscore wire form recovered to canonical before extraction
        ("KFA_07", "7"),
        ("GHT_01", "1"),
        # Underscore without hyphen path (digits at end)
        ("step_004", "4"),
        # No numeric suffix → no prefix
        ("PLAN-RV", ""),
        ("abc", ""),
        ("", ""),
        # Non-numeric segment after last hyphen falls back to trailing digits
        ("REV-2a-3", "3"),
    ],
)
def test_numeric_step_prefix_extracts_trailing_number(step_id: str, expected: str) -> None:
    assert numeric_step_prefix(step_id) == expected


def test_plan_panel_renders_full_step_id(tmp_path) -> None:
    """Plan panel rows render the full scoped step id (e.g. ``KFA-01``).

    Dependency hints keep the compact numeric-only form for inline brevity.
    """
    from soothe_cli.tui.widgets.messages.cognition_goal_tree import (
        CognitionGoalTreeMessage,
    )

    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-fullid")
    tree.sync_plan_steps(
        [
            {"id": "KFA-01", "description": "Read"},
            {"id": "KFA-02", "description": "Edit", "dependencies": ["KFA-01"]},
            {"id": "PLAN-RV", "description": "Review"},
        ]
    )
    tree.set_step_phase("KFA-01", "running", description="Read")

    content = tree.plan_quick_view_content()
    plain = content.plain

    # Full scoped id is now the visible step prefix.
    assert "KFA-01:" in plain
    assert "KFA-02:" in plain
    assert "PLAN-RV:" in plain
    # Dependency hint stays compact (numeric-only reference).
    assert "(→ 1)" in plain
    # Description still rendered.
    assert "Read" in plain
    assert "Edit" in plain
    assert "Review" in plain


def test_display_step_id_normalizes_wire_form() -> None:
    """Wire-form underscore fragments resolve to the canonical hyphen form."""
    assert display_step_id("KFA_07") == "KFA-07"
    assert display_step_id("KFA-07") == "KFA-07"
    assert display_step_id("STEP-1") == "STEP-1"
    assert display_step_id("01") == "01"
    assert display_step_id("PLAN-RV") == "PLAN-RV"
    assert display_step_id("") == ""
    assert display_step_id("   ") == ""
