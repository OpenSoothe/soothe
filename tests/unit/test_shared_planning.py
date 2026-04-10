"""Tests for shared planner utilities (_shared.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.planning._shared import (
    parse_plan_from_text,
    reflect_heuristic,
    reflect_with_llm,
)
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanStep,
    StepResult,
)


class TestParsePlanFromText:
    """Tests for parse_plan_from_text."""

    def test_step_n_format(self) -> None:
        text = (
            "**Step 1: Gather requirements**\n"
            "- Description: Collect all info\n\n"
            "**Step 2: Design the solution**\n"
            "- Description: Create architecture\n\n"
            "**Step 3: Implement**\n"
        )
        plan = parse_plan_from_text("Build app", text)
        assert plan.goal == "Build app"
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "Gather requirements"
        assert plan.steps[1].description == "Design the solution"
        assert plan.steps[2].description == "Implement"

    def test_numbered_list_fallback(self) -> None:
        text = "1. First do this thing\n2. Then do that thing\n3. Finally verify"
        plan = parse_plan_from_text("My goal", text)
        assert len(plan.steps) == 3
        assert "First do this thing" in plan.steps[0].description

    def test_empty_text_fallback(self) -> None:
        plan = parse_plan_from_text("Fallback goal", "")
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "Fallback goal"

    def test_short_lines_filtered(self) -> None:
        text = "ok\n\nThis is a proper step description\n\nno"
        plan = parse_plan_from_text("Goal", text)
        assert len(plan.steps) == 1
        assert "proper step" in plan.steps[0].description


class TestReflectHeuristic:
    """Tests for reflect_heuristic."""

    def test_all_success(self) -> None:
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", description="A"),
                PlanStep(id="s2", description="B"),
            ],
        )
        results = [
            StepResult(step_id="s1", success=True, outcome={"type": "generic", "size_bytes": 2}),
            StepResult(step_id="s2", success=True, outcome={"type": "generic", "size_bytes": 2}),
        ]
        ref = reflect_heuristic(plan, results)
        assert not ref.should_revise
        assert "2/2" in ref.assessment
        assert ref.goal_directives == []

    def test_direct_failure(self) -> None:
        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="A")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "error",
            )
        ]
        ref = reflect_heuristic(plan, results)
        assert ref.should_revise
        assert "s1" in ref.failed_details

    def test_blocked_by_dependency(self) -> None:
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", description="A"),
                PlanStep(id="s2", description="B", depends_on=["s1"]),
            ],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "err",
            ),
            StepResult(
                step_id="s2",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "blocked",
            ),
        ]
        ref = reflect_heuristic(plan, results)
        assert "s2" in ref.blocked_steps
        assert "s1" not in ref.blocked_steps

    def test_prerequisite_directive_generation(self) -> None:
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", description="Install lib", result="library not found"),
            ],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "lib not found",
            )
        ]
        goal_ctx = GoalContext(
            current_goal_id="g1",
            all_goals=[{"id": "g1", "priority": 50}],
        )
        ref = reflect_heuristic(plan, results, goal_ctx)
        assert len(ref.goal_directives) == 1
        assert ref.goal_directives[0].action == "create"
        assert ref.goal_directives[0].priority == 60

    def test_no_directives_without_goal_context(self) -> None:
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", description="Install lib", result="not found"),
            ],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "not found",
            )
        ]
        ref = reflect_heuristic(plan, results, goal_context=None)
        assert ref.goal_directives == []


class TestReflectWithLLM:
    """Tests for reflect_with_llm."""

    @pytest.mark.asyncio
    async def test_all_success_skips_llm(self) -> None:
        model = MagicMock()
        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="A")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=True,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "True" == "True" else "ok",
            )
        ]

        ref = await reflect_with_llm(model, plan, results)
        assert not ref.should_revise
        model.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_called_on_failure(self) -> None:
        mock_response = MagicMock()
        mock_response.content = (
            '{"assessment": "step failed", "should_revise": true, '
            '"feedback": "retry", "blocked_steps": [], '
            '"failed_details": {"s1": "error"}, "goal_directives": []}'
        )
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=mock_response)

        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="A")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "error",
            )
        ]

        ref = await reflect_with_llm(model, plan, results)
        assert ref.should_revise
        assert ref.assessment == "step failed"
        model.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_heuristic(self) -> None:
        model = MagicMock()
        model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="A")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "error",
            )
        ]

        ref = await reflect_with_llm(model, plan, results)
        assert ref.should_revise
        assert "s1" in ref.failed_details

    @pytest.mark.asyncio
    async def test_llm_returns_directives(self) -> None:
        mock_response = MagicMock()
        mock_response.content = (
            '{"assessment": "missing prereq", "should_revise": true, '
            '"feedback": "install dep first", "blocked_steps": [], '
            '"failed_details": {"s1": "not installed"}, '
            '"goal_directives": [{"action": "create", '
            '"description": "Install dependency", "priority": 80, '
            '"rationale": "prereq missing"}]}'
        )
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=mock_response)

        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="Use library")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "not installed",
            )
        ]
        goal_ctx = GoalContext(current_goal_id="g1")

        ref = await reflect_with_llm(model, plan, results, goal_ctx)
        assert len(ref.goal_directives) == 1
        assert ref.goal_directives[0].action == "create"
        assert ref.goal_directives[0].priority == 80

    @pytest.mark.asyncio
    async def test_llm_invalid_json_falls_back(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "This is not valid JSON at all"
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=mock_response)

        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", description="A")],
        )
        results = [
            StepResult(
                step_id="s1",
                success=False,
                outcome={"type": "generic", "size_bytes": 2},
                error=None if "False" == "True" else "err",
            )
        ]

        ref = await reflect_with_llm(model, plan, results)
        assert ref.should_revise
        assert "s1" in ref.failed_details
