"""Tests for numeric step id display formatting in the plan panel."""

from __future__ import annotations

import pytest

from soothe_cli.runtime.presentation.step_id_format import numeric_step_prefix


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


def test_numeric_step_prefix_preserves_display_in_tree(tmp_path) -> None:
    """Plan panel rows render the numeric prefix, never the scoped id."""
    from soothe_cli.tui.widgets.messages.cognition_goal_tree import (
        CognitionGoalTreeMessage,
    )

    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-numeric")
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

    # Numeric prefixes present for scoped ids
    assert "1:" in plain
    assert "2:" in plain
    # Dependency hint uses numeric-only reference
    assert "(→ 1)" in plain
    # No numeric suffix → no prefix and no raw id leaked
    assert "PLAN-RV" not in plain
    assert "KFA-01" not in plain
    assert "KFA-02" not in plain
    # Description still rendered
    assert "Review" in plain
