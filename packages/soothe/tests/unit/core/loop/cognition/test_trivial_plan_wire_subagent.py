"""Tests for explicit subagent wiring in trivial-branch plans."""

from __future__ import annotations

from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.state.schemas import resolve_wire_subagent


def test_resolve_wire_subagent_accepts_pass2_hint() -> None:
    assert resolve_wire_subagent(wire_subagent="browser_use") == "browser_use"
    assert resolve_wire_subagent(wire_subagent="unknown") is None


def test_build_trivial_plan_wires_browser_use_from_pass2() -> None:
    plan = build_trivial_plan(
        "get weather at beijing",
        wire_subagent="browser_use",
    )
    step = plan.decision.steps[0]
    assert step.wire_subagent == "browser_use"
    assert step.execution_hint == "subagent"
    assert step.subagent == "browser_use"


def test_build_trivial_plan_leaves_wire_subagent_none_for_generic_goal() -> None:
    plan = build_trivial_plan("list files in this directory")
    step = plan.decision.steps[0]
    assert step.wire_subagent is None
