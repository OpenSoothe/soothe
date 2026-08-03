"""Unit tests for mid-loop intake-tier policy (IG-676)."""

from __future__ import annotations

from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.mid_loop_intake import (
    mid_loop_allow_inventory,
    mid_loop_skip_continuation_assess,
    mid_loop_use_lightweight_generate,
)


def test_skip_continuation_assess_simple_and_complex_only() -> None:
    assert mid_loop_skip_continuation_assess(IntakeLabel.SIMPLE) is True
    assert mid_loop_skip_continuation_assess(IntakeLabel.COMPLEX) is True
    assert mid_loop_skip_continuation_assess(IntakeLabel.TRIVIAL) is False
    assert mid_loop_skip_continuation_assess(None) is False


def test_lightweight_generate_simple_only() -> None:
    assert mid_loop_use_lightweight_generate(IntakeLabel.SIMPLE) is True
    assert mid_loop_use_lightweight_generate(IntakeLabel.COMPLEX) is False
    assert mid_loop_use_lightweight_generate(IntakeLabel.TRIVIAL) is False


def test_inventory_skipped_for_trivial() -> None:
    assert (
        mid_loop_allow_inventory(
            intake_label=IntakeLabel.TRIVIAL,
            projection_mode="mid_goal",
            has_step_results=True,
            has_execute_ledger=True,
        )
        is False
    )


def test_inventory_skipped_for_new_goal_without_evidence() -> None:
    assert (
        mid_loop_allow_inventory(
            intake_label=IntakeLabel.SIMPLE,
            projection_mode="new_goal",
            has_step_results=False,
            has_execute_ledger=False,
        )
        is False
    )


def test_inventory_allowed_for_simple_mid_iteration() -> None:
    assert (
        mid_loop_allow_inventory(
            intake_label=IntakeLabel.SIMPLE,
            projection_mode="mid_goal",
            has_step_results=True,
            has_execute_ledger=True,
        )
        is True
    )


def test_inventory_allowed_for_complex_with_evidence() -> None:
    assert (
        mid_loop_allow_inventory(
            intake_label=IntakeLabel.COMPLEX,
            projection_mode="new_goal",
            has_step_results=False,
            has_execute_ledger=True,
        )
        is True
    )
