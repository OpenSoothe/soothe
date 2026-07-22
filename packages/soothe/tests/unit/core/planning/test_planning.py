"""Tests for planning implementation (LLMPlanner)."""

from unittest.mock import MagicMock

from soothe.sloop.cognition.parser import parse_plan_from_text
from soothe.sloop.cognition.planner import LLMPlanner


class TestLLMPlanner:
    """Unit tests for LLMPlanner."""

    def test_initialization(self) -> None:
        """Test initialization with a model."""
        mock_model = MagicMock()
        planner = LLMPlanner(mock_model)

        assert planner._model == mock_model


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
