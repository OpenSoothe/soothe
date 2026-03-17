"""Tests for plan models: StepReport, GoalReport, PlanStep (soothe.protocols.planner)."""

import pytest

from soothe.protocols.planner import GoalReport, PlanStep, StepReport


class TestStepReport:
    """Tests for StepReport model."""

    def test_step_report_creation(self) -> None:
        report = StepReport(
            step_id="s1",
            description="Do something",
            status="completed",
            result="Done",
            duration_ms=100,
        )
        assert report.step_id == "s1"
        assert report.description == "Do something"
        assert report.status == "completed"
        assert report.result == "Done"
        assert report.duration_ms == 100

    @pytest.mark.parametrize("status", ["completed", "failed", "skipped"])
    def test_step_report_status_literal(self, status: str) -> None:
        report = StepReport(step_id="s1", description="x", status=status)
        assert report.status == status


class TestGoalReport:
    """Tests for GoalReport model."""

    def test_goal_report_creation(self) -> None:
        step_reports = [
            StepReport(step_id="s1", description="Step 1", status="completed"),
        ]
        report = GoalReport(
            goal_id="g1",
            description="Goal 1",
            step_reports=step_reports,
        )
        assert report.goal_id == "g1"
        assert report.description == "Goal 1"
        assert len(report.step_reports) == 1
        assert report.step_reports[0].step_id == "s1"

    def test_goal_report_defaults(self) -> None:
        report = GoalReport(goal_id="g1", description="Goal")
        assert report.summary == ""
        assert report.status == "completed"
        assert report.duration_ms == 0


class TestPlanStepDependsOn:
    """Tests for PlanStep.depends_on."""

    def test_plan_step_depends_on_default(self) -> None:
        step = PlanStep(id="s1", description="Step")
        assert step.depends_on == []

    def test_plan_step_depends_on_custom(self) -> None:
        step = PlanStep(id="s1", description="Step", depends_on=["a", "b"])
        assert step.depends_on == ["a", "b"]


class TestSerialization:
    """Tests for model_dump/model_validate round-trip."""

    def test_step_report_serialization(self) -> None:
        report = StepReport(
            step_id="s1",
            description="Do something",
            status="failed",
            result="Error",
            duration_ms=50,
        )
        data = report.model_dump()
        restored = StepReport.model_validate(data)
        assert restored.step_id == report.step_id
        assert restored.description == report.description
        assert restored.status == report.status
        assert restored.result == report.result
        assert restored.duration_ms == report.duration_ms

    def test_goal_report_serialization(self) -> None:
        report = GoalReport(
            goal_id="g1",
            description="Goal",
            step_reports=[
                StepReport(step_id="s1", description="S1", status="completed"),
            ],
            summary="Done",
            status="completed",
            duration_ms=200,
        )
        data = report.model_dump()
        restored = GoalReport.model_validate(data)
        assert restored.goal_id == report.goal_id
        assert restored.description == report.description
        assert len(restored.step_reports) == 1
        assert restored.step_reports[0].step_id == "s1"
        assert restored.summary == report.summary
        assert restored.status == report.status
        assert restored.duration_ms == report.duration_ms
