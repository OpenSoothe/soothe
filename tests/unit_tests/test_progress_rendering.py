"""Tests for TUI/headless progress rendering behavior."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from soothe.cli.main import _render_progress_event
from soothe.cli.tui_shared import (
    TuiState,
    _handle_protocol_event,
    _handle_subagent_text_activity,
    _set_plan_step_status_by_id,
    render_plan_tree,
)
from soothe.protocols.planner import Plan, PlanStep


def test_render_progress_event_policy_includes_profile(capsys) -> None:
    _render_progress_event({"type": "soothe.policy.checked", "verdict": "allow", "profile": "strict"})
    captured = capsys.readouterr()
    assert "[policy] allow (profile=strict)" in captured.err


def test_tui_policy_activity_includes_profile() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.policy.checked", "verdict": "allow", "profile": "standard"},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "Policy: allow (profile=standard)" in state.activity_lines[0].plain


def test_subagent_text_activity_respects_verbosity() -> None:
    state = TuiState()
    _handle_subagent_text_activity(("tools:abc",), "working on it", state, verbosity="normal")
    assert state.activity_lines == []

    _handle_subagent_text_activity(("tools:abc",), "working on it", state, verbosity="detailed")
    assert len(state.activity_lines) == 1
    assert "Text: working on it" in state.activity_lines[0].plain


def test_plan_batch_started_renders() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.plan.batch_started", "parallel_count": 2},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "parallel" in state.activity_lines[0].plain


def test_plan_step_started_by_id() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.plan.step_started", "step_id": "s1", "description": "do something"},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "s1" in state.activity_lines[0].plain


def test_plan_step_started_with_batch_index() -> None:
    """Test step_started includes batch_index (RFC-0009)."""
    state = TuiState()
    _handle_protocol_event(
        {
            "type": "soothe.plan.step_started",
            "step_id": "s1",
            "description": "do something",
            "depends_on": [],
            "batch_index": 0,
        },
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "s1" in state.activity_lines[0].plain


def test_plan_step_completed_by_id_with_duration() -> None:
    state = TuiState()
    _handle_protocol_event(
        {
            "type": "soothe.plan.step_completed",
            "step_id": "s1",
            "success": True,
            "duration_ms": 1234,
        },
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "done" in state.activity_lines[0].plain
    assert "1234ms" in state.activity_lines[0].plain


def test_plan_step_failed_renders() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.plan.step_failed", "step_id": "s1", "error": "timeout"},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "FAILED" in state.activity_lines[0].plain
    assert "timeout" in state.activity_lines[0].plain


def test_plan_step_failed_with_blocked_steps() -> None:
    """Test step_failed includes blocked_steps (RFC-0009)."""
    state = TuiState()
    _handle_protocol_event(
        {
            "type": "soothe.plan.step_failed",
            "step_id": "s1",
            "error": "dependency failed",
            "blocked_steps": ["s2", "s3"],
        },
        state,
        verbosity="normal",
    )
    # Verify event is handled and shows failure (blocked_steps is emitted but not displayed in TUI)
    assert len(state.activity_lines) == 1
    assert "FAILED" in state.activity_lines[0].plain
    assert "dependency failed" in state.activity_lines[0].plain


def test_goal_batch_started_renders() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.goal.batch_started", "parallel_count": 3},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "parallel" in state.activity_lines[0].plain


def test_set_plan_step_status_by_id() -> None:
    state = TuiState()
    state.current_plan = Plan(
        goal="test goal",
        steps=[
            PlanStep(id="s1", description="step 1", status="pending"),
            PlanStep(id="s2", description="step 2", status="pending"),
        ],
    )
    _set_plan_step_status_by_id(state, "s1", "in_progress")
    assert state.current_plan.steps[0].status == "in_progress"
    assert state.current_plan.steps[1].status == "pending"

    _set_plan_step_status_by_id(state, "s2", "completed")
    assert state.current_plan.steps[1].status == "completed"


def test_render_plan_tree_with_depends_on() -> None:
    plan = Plan(
        goal="test goal",
        steps=[
            PlanStep(id="step_1", description="first step", status="completed", depends_on=[]),
            PlanStep(id="step_2", description="second step", status="pending", depends_on=["step_1"]),
        ],
    )
    tree = render_plan_tree(plan)
    buf = StringIO()
    Console(file=buf).print(tree)
    tree_str = buf.getvalue()
    assert "(< step_1)" in tree_str


def test_plan_step_started_backward_compat() -> None:
    state = TuiState()
    _handle_protocol_event(
        {"type": "soothe.plan.step_started", "index": 0, "description": "legacy step"},
        state,
        verbosity="normal",
    )
    assert len(state.activity_lines) == 1
    assert "Step 1" in state.activity_lines[0].plain
    assert "legacy step" in state.activity_lines[0].plain
