"""Tests for planning implementation (DirectPlanner)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.backends.planning.direct import DirectPlanner
from soothe.protocols.planner import Plan, PlanContext, PlanStep, StepResult


class TestDirectPlanner:
    """Unit tests for DirectPlanner."""

    def test_initialization(self) -> None:
        """Test initialization with a model."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        assert planner._model == mock_model

    @pytest.mark.asyncio
    async def test_create_plan_success(self) -> None:
        """Test successful plan creation."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()

        expected_plan = Plan(
            goal="test goal",
            steps=[
                PlanStep(id="step_1", description="First step", execution_hint="tool"),
                PlanStep(id="step_2", description="Second step", execution_hint="subagent"),
            ],
        )
        mock_structured.ainvoke = AsyncMock(return_value=expected_plan)
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        planner = DirectPlanner(mock_model)
        context = PlanContext(available_capabilities=["tool1", "tool2"])

        plan = await planner.create_plan("test goal", context)

        assert plan.goal == "test goal"
        assert len(plan.steps) == 2
        assert plan.steps[0].id == "step_1"

    @pytest.mark.asyncio
    async def test_create_plan_fallback_on_error(self) -> None:
        """Test plan creation fallback when structured output fails."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(side_effect=Exception("Model error"))
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        planner = DirectPlanner(mock_model)
        context = PlanContext()

        plan = await planner.create_plan("test goal", context)

        # Should return fallback plan with single step
        assert plan.goal == "test goal"
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "test goal"

    @pytest.mark.asyncio
    async def test_create_plan_includes_context(self) -> None:
        """Test that plan creation includes context information."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()

        expected_plan = Plan(
            goal="test goal",
            steps=[PlanStep(id="step_1", description="Step", execution_hint="tool")],
        )
        mock_structured.ainvoke = AsyncMock(return_value=expected_plan)
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        planner = DirectPlanner(mock_model)
        context = PlanContext(
            available_capabilities=["tool1", "tool2"],
            completed_steps=[StepResult(step_id="prev_step", success=True, output="done")],
        )

        await planner.create_plan("test goal", context)

        # Verify the prompt includes context
        call_args = mock_structured.ainvoke.call_args[0][0]
        assert "tool1" in call_args
        assert "tool2" in call_args
        assert "prev_step" in call_args

    @pytest.mark.asyncio
    async def test_revise_plan_success(self) -> None:
        """Test successful plan revision."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()

        original_plan = Plan(
            goal="test goal",
            steps=[PlanStep(id="step_1", description="Original step", execution_hint="tool")],
        )

        revised_plan = Plan(
            goal="test goal",
            steps=[
                PlanStep(id="step_1", description="Revised step", execution_hint="tool"),
                PlanStep(id="step_2", description="New step", execution_hint="subagent"),
            ],
        )
        mock_structured.ainvoke = AsyncMock(return_value=revised_plan)
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        planner = DirectPlanner(mock_model)

        result = await planner.revise_plan(original_plan, "Add more steps")

        assert result.status == "revised"
        assert len(result.steps) == 2

    @pytest.mark.asyncio
    async def test_revise_plan_fallback_on_error(self) -> None:
        """Test plan revision fallback when structured output fails."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(side_effect=Exception("Model error"))
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        planner = DirectPlanner(mock_model)
        original_plan = Plan(
            goal="test goal",
            steps=[PlanStep(id="step_1", description="Step", execution_hint="tool")],
        )

        result = await planner.revise_plan(original_plan, "feedback")

        # Should return original plan
        assert result == original_plan

    @pytest.mark.asyncio
    async def test_reflect_all_steps_succeeded(self) -> None:
        """Test reflection when all steps succeeded."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        plan = Plan(
            goal="test goal",
            steps=[
                PlanStep(id="step_1", description="Step 1", execution_hint="tool"),
                PlanStep(id="step_2", description="Step 2", execution_hint="subagent"),
            ],
        )

        step_results = [
            StepResult(step_id="step_1", success=True, output="done"),
            StepResult(step_id="step_2", success=True, output="done"),
        ]

        reflection = await planner.reflect(plan, step_results)

        assert "2/2 steps completed successfully" in reflection.assessment
        assert reflection.should_revise is False
        assert reflection.feedback == ""

    @pytest.mark.asyncio
    async def test_reflect_some_steps_failed(self) -> None:
        """Test reflection when some steps failed."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        plan = Plan(
            goal="test goal",
            steps=[
                PlanStep(id="step_1", description="Step 1", execution_hint="tool"),
                PlanStep(id="step_2", description="Step 2", execution_hint="subagent"),
            ],
        )

        step_results = [
            StepResult(step_id="step_1", success=True, output="done"),
            StepResult(step_id="step_2", success=False, output="failed"),
        ]

        reflection = await planner.reflect(plan, step_results)

        assert "1/2 steps completed" in reflection.assessment
        assert "1 failed" in reflection.assessment
        assert reflection.should_revise is True
        assert "step_2" in reflection.feedback

    @pytest.mark.asyncio
    async def test_reflect_all_steps_failed(self) -> None:
        """Test reflection when all steps failed."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        plan = Plan(
            goal="test goal",
            steps=[
                PlanStep(id="step_1", description="Step 1", execution_hint="tool"),
                PlanStep(id="step_2", description="Step 2", execution_hint="subagent"),
            ],
        )

        step_results = [
            StepResult(step_id="step_1", success=False, output="failed"),
            StepResult(step_id="step_2", success=False, output="failed"),
        ]

        reflection = await planner.reflect(plan, step_results)

        assert "0/2 steps completed" in reflection.assessment
        assert "2 failed" in reflection.assessment
        assert reflection.should_revise is True

    def test_build_plan_prompt_basic(self) -> None:
        """Test building plan prompt with basic goal."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        context = PlanContext()
        prompt = planner._build_plan_prompt("test goal", context)

        assert "test goal" in prompt
        assert "plan" in prompt.lower()

    def test_build_plan_prompt_with_capabilities(self) -> None:
        """Test building plan prompt with available capabilities."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        context = PlanContext(available_capabilities=["tool1", "tool2", "agent1"])
        prompt = planner._build_plan_prompt("test goal", context)

        assert "tool1" in prompt
        assert "tool2" in prompt
        assert "agent1" in prompt

    def test_build_plan_prompt_with_completed_steps(self) -> None:
        """Test building plan prompt with completed steps."""
        mock_model = MagicMock()
        planner = DirectPlanner(mock_model)

        completed = [
            StepResult(step_id="step_1", success=True, output="done"),
            StepResult(step_id="step_2", success=True, output="done"),
        ]
        context = PlanContext(completed_steps=completed)
        prompt = planner._build_plan_prompt("test goal", context)

        assert "step_1" in prompt
        assert "step_2" in prompt
