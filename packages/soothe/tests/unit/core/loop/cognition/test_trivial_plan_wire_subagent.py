"""Tests for explicit subagent wiring in trivial-branch plans."""

from __future__ import annotations

from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.state.schemas import infer_explicit_wire_subagent_from_goal


def test_infer_explicit_wire_subagent_from_goal_browser_use() -> None:
    assert (
        infer_explicit_wire_subagent_from_goal("use browser_use to get weather at beijing")
        == "browser_use"
    )


def test_build_trivial_plan_wires_browser_use_when_named_in_goal() -> None:
    plan = build_trivial_plan("use browser_use to get weather at beijing")
    step = plan.decision.steps[0]
    assert step.wire_subagent == "browser_use"
    assert step.execution_hint == "subagent"
    assert step.subagent == "browser_use"


def test_build_trivial_plan_leaves_wire_subagent_none_for_generic_goal() -> None:
    plan = build_trivial_plan("list files in this directory")
    step = plan.decision.steps[0]
    assert step.wire_subagent is None
