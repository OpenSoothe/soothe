"""Tests for TUI/headless progress rendering behavior."""

from __future__ import annotations

from rich.console import Console

from soothe.protocols.planner import Plan, PlanStep
from soothe.ux.cli.progress import render_progress_event
from soothe.ux.core.rendering import render_plan_tree


def test_render_progress_event_policy_allow_suppressed(capsys) -> None:
    """Policy 'allow' events are not handled by the simplified renderer (RFC-0019)."""
    event_type = "soothe.protocol.policy.checked"
    render_progress_event(event_type, {"type": event_type, "verdict": "allow", "profile": "strict"})
    captured = capsys.readouterr()
    # Policy events are not rendered by the simplified renderer
    assert captured.err == ""


def test_render_progress_event_policy_deny_shown(capsys) -> None:
    """Policy events are not handled by the simplified renderer (RFC-0019)."""
    event_type = "soothe.protocol.policy.checked"
    data = {"type": event_type, "verdict": "deny", "profile": "strict"}
    render_progress_event(event_type, data)
    captured = capsys.readouterr()
    # Policy events are not rendered by the simplified renderer
    assert captured.err == ""


def test_render_progress_event_policy_allow_shown_in_debug(capsys) -> None:
    """Policy events are not handled by the simplified renderer (RFC-0019)."""
    event_type = "soothe.protocol.policy.checked"
    data = {"type": event_type, "verdict": "allow", "profile": "strict"}
    render_progress_event(event_type, data)
    captured = capsys.readouterr()
    # Policy events are not rendered by the simplified renderer
    assert captured.err == ""


def test_render_progress_event_policy_denied_shown(capsys) -> None:
    """Policy events are not handled by the simplified renderer (RFC-0019)."""
    event_type = "soothe.protocol.policy.denied"
    render_progress_event(event_type, {"type": event_type, "reason": "unauthorized action", "profile": "strict"})
    captured = capsys.readouterr()
    # Policy events are not rendered by the simplified renderer
    assert captured.err == ""


def test_plan_tree_renders() -> None:
    """Plan tree renders with status markers."""
    plan = Plan(
        goal="Test goal",
        steps=[
            PlanStep(id="s1", description="Step 1", status="completed"),
            PlanStep(id="s2", description="Step 2", status="in_progress"),
            PlanStep(id="s3", description="Step 3", status="pending"),
        ],
    )

    tree = render_plan_tree(plan)
    # Verify tree was created
    assert tree is not None


def test_plan_tree_with_dependencies() -> None:
    """Plan tree shows dependencies."""
    plan = Plan(
        goal="Test goal",
        steps=[
            PlanStep(id="s1", description="Step 1", status="completed", depends_on=[]),
            PlanStep(id="s2", description="Step 2", status="pending", depends_on=["s1"]),
        ],
    )

    tree = render_plan_tree(plan)
    assert tree is not None


def test_plan_tree_with_activity() -> None:
    """Plan tree shows current activity for in-progress steps."""
    plan = Plan(
        goal="Test goal",
        steps=[
            PlanStep(
                id="s1",
                description="Step 1",
                status="in_progress",
                current_activity="Running tests",
            ),
        ],
    )

    tree = render_plan_tree(plan)
    assert tree is not None


def test_plan_tree_with_general_activity() -> None:
    """Plan tree shows general activity."""
    plan = Plan(
        goal="Test goal",
        general_activity="Loading configuration",
        steps=[],
    )

    tree = render_plan_tree(plan)
    assert tree is not None
