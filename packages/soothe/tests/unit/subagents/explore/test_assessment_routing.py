"""Tests for explore post-assessment routing (IG-326)."""

from __future__ import annotations

import pytest

from soothe.subagents.explore.engine import route_after_explore_assessment


@pytest.mark.parametrize(
    ("iters", "max_it", "decision", "expected"),
    [
        (0, 4, "finish", "synthesize"),
        (1, 4, "finish", "synthesize"),
        (1, 4, "continue", "plan_search"),
        (1, 4, "adjust", "plan_search"),
        (4, 4, "continue", "synthesize"),
        (3, 4, "continue", "plan_search"),
    ],
)
def test_route_after_explore_assessment(
    iters: int, max_it: int, decision: str, expected: str
) -> None:
    assert route_after_explore_assessment(iters, max_it, decision) == expected


def test_invalid_decision_treated_as_finish() -> None:
    assert route_after_explore_assessment(0, 4, "nope") == "synthesize"
