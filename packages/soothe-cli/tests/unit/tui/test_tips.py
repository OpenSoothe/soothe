"""Tests for the rotating session tip pool surfaced in the status bar."""

from __future__ import annotations

import random

from soothe_cli.tui.tips import SESSION_TIPS, TipRotator, pick_session_tip


def test_session_tips_is_non_empty_str_list() -> None:
    assert isinstance(SESSION_TIPS, list)
    assert SESSION_TIPS, "SESSION_TIPS must not be empty"
    assert all(isinstance(tip, str) and tip for tip in SESSION_TIPS)


def test_session_tips_contains_plan_generation_tips() -> None:
    """Plan-generation tips must be present in the tip pool."""
    plan_tips = [t for t in SESSION_TIPS if "plan" in t.lower()]
    assert plan_tips, "expected at least one plan-related tip in SESSION_TIPS"


def test_plan_tips_reference_action_triggers() -> None:
    """Plan tips should surface actionable bindings (ctrl+t, shift+tab, or /plan)."""
    plan_tips = [t for t in SESSION_TIPS if "plan" in t.lower()]
    assert any("ctrl+t" in t.lower() for t in plan_tips), "expected a ctrl+t plan-quick-view tip"
    assert any("shift+tab" in t.lower() for t in plan_tips), "expected a shift+tab Plan mode tip"
    assert any("/plan" in t.lower() for t in plan_tips), "expected a /plan command tip"


def test_pick_session_tip_returns_member_of_pool() -> None:
    random.seed(42)
    for _ in range(20):
        tip = pick_session_tip()
        assert tip in SESSION_TIPS


def test_pick_session_tip_returns_str() -> None:
    assert isinstance(pick_session_tip(), str)


def test_tip_rotator_returns_pool_members() -> None:
    """Each rotated tip must be a member of the pool."""
    rotator = TipRotator()
    for _ in range(len(SESSION_TIPS) * 3):
        assert rotator.next_tip() in SESSION_TIPS


def test_tip_rotator_cycles_through_full_pool() -> None:
    """One full pass over the pool covers every tip exactly once."""
    rotator = TipRotator()
    seen = {rotator.next_tip() for _ in range(len(SESSION_TIPS))}
    assert seen == set(SESSION_TIPS)


def test_tip_rotator_avoids_immediate_repeat() -> None:
    """Consecutive tips should differ while the pool has more than one entry."""
    rotator = TipRotator()
    previous = rotator.next_tip()
    for _ in range(len(SESSION_TIPS) * 4):
        current = rotator.next_tip()
        assert current != previous, "rotator repeated a tip back-to-back"
        previous = current


def test_tip_rotator_returns_str() -> None:
    assert isinstance(TipRotator().next_tip(), str)


def test_tip_rotator_custom_pool() -> None:
    """A rotator seeded with a custom pool stays within that pool."""
    custom = ["alpha", "beta", "gamma"]
    rotator = TipRotator(tips=custom)
    for _ in range(10):
        assert rotator.next_tip() in custom


def test_tip_rotator_empty_pool_returns_empty_string() -> None:
    assert TipRotator(tips=[]).next_tip() == ""
