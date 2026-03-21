"""Tests for goal management tools (RFC-0007, RFC-0016)."""

import pytest

from soothe.cognition import GoalEngine
from soothe.tools.goals import (
    CompleteGoalTool,
    CreateGoalTool,
    FailGoalTool,
    ListGoalsTool,
    create_goals_tools,
)


class TestGoalTools:
    """Unit tests for goal management tools."""

    def test_create_returns_four_tools(self) -> None:
        """Should return 4 single-purpose tools."""
        engine = GoalEngine()
        tools = create_goals_tools(engine)
        assert len(tools) == 4
        assert isinstance(tools[0], CreateGoalTool)
        assert isinstance(tools[1], ListGoalsTool)
        assert isinstance(tools[2], CompleteGoalTool)
        assert isinstance(tools[3], FailGoalTool)

    @pytest.mark.asyncio
    async def test_create_goal(self) -> None:
        """Test creating a goal."""
        engine = GoalEngine()
        tool = CreateGoalTool(goal_engine=engine)
        result = await tool._arun(description="New goal", priority=70)
        assert result["id"]
        assert result["description"] == "New goal"
        assert result["priority"] == 70

    @pytest.mark.asyncio
    async def test_create_goal_without_description(self) -> None:
        """Test creating a goal without description should fail."""
        engine = GoalEngine()
        tool = CreateGoalTool(goal_engine=engine)
        result = await tool._arun(description="")
        assert "error" in result or not result.get("id")

    @pytest.mark.asyncio
    async def test_list_goals(self) -> None:
        """Test listing goals."""
        engine = GoalEngine()
        create_tool = CreateGoalTool(goal_engine=engine)
        list_tool = ListGoalsTool(goal_engine=engine)

        await create_tool._arun(description="Goal A")
        await create_tool._arun(description="Goal B")

        result = await list_tool._arun()
        assert len(result["goals"]) == 2

    @pytest.mark.asyncio
    async def test_list_goals_with_status_filter(self) -> None:
        """Test listing goals with status filter."""
        engine = GoalEngine()
        create_tool = CreateGoalTool(goal_engine=engine)
        complete_tool = CompleteGoalTool(goal_engine=engine)
        list_tool = ListGoalsTool(goal_engine=engine)

        create_result = await create_tool._arun(description="Goal A")
        goal_id = create_result["id"]
        await complete_tool._arun(goal_id=goal_id)

        pending = await list_tool._arun(status="pending")
        assert len(pending["goals"]) == 0

        completed = await list_tool._arun(status="completed")
        assert len(completed["goals"]) == 1

    @pytest.mark.asyncio
    async def test_complete_goal(self) -> None:
        """Test completing a goal."""
        engine = GoalEngine()
        create_tool = CreateGoalTool(goal_engine=engine)
        complete_tool = CompleteGoalTool(goal_engine=engine)

        create_result = await create_tool._arun(description="To complete")
        goal_id = create_result["id"]
        result = await complete_tool._arun(goal_id=goal_id)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_goal_not_found(self) -> None:
        """Test completing a non-existent goal."""
        engine = GoalEngine()
        complete_tool = CompleteGoalTool(goal_engine=engine)
        result = await complete_tool._arun(goal_id="nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fail_goal(self) -> None:
        """Test failing a goal."""
        engine = GoalEngine()
        create_tool = CreateGoalTool(goal_engine=engine)
        fail_tool = FailGoalTool(goal_engine=engine)

        create_result = await create_tool._arun(description="To fail")
        goal_id = create_result["id"]
        result = await fail_tool._arun(goal_id=goal_id, error="test error")
        # With max_retries=2, first failure retries
        assert result["status"] == "pending"
        assert result["retry_count"] == 1

    def test_tool_names(self) -> None:
        """Test tool names are correct."""
        engine = GoalEngine()
        create_tool = CreateGoalTool(goal_engine=engine)
        list_tool = ListGoalsTool(goal_engine=engine)
        complete_tool = CompleteGoalTool(goal_engine=engine)
        fail_tool = FailGoalTool(goal_engine=engine)

        assert create_tool.name == "create_goal"
        assert list_tool.name == "list_goals"
        assert complete_tool.name == "complete_goal"
        assert fail_tool.name == "fail_goal"
