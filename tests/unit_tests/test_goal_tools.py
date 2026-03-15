"""Tests for manage_goals tool (RFC-0007)."""

import pytest

from soothe.core.goal_engine import GoalEngine
from soothe.tools.goals import ManageGoalsTool, create_goal_tools


class TestManageGoalsTool:
    """Unit tests for ManageGoalsTool."""

    def _make_tool(self) -> ManageGoalsTool:
        engine = GoalEngine()
        tools = create_goal_tools(engine)
        assert len(tools) == 1
        assert isinstance(tools[0], ManageGoalsTool)
        return tools[0]

    @pytest.mark.asyncio
    async def test_create_action(self):
        tool = self._make_tool()
        result = await tool._arun(action="create", description="New goal", priority=70)
        assert "created" in result
        assert result["created"]["description"] == "New goal"
        assert result["created"]["priority"] == 70

    @pytest.mark.asyncio
    async def test_create_without_description(self):
        tool = self._make_tool()
        result = await tool._arun(action="create")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_action(self):
        tool = self._make_tool()
        await tool._arun(action="create", description="Goal A")
        await tool._arun(action="create", description="Goal B")
        result = await tool._arun(action="list")
        assert len(result["goals"]) == 2

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        tool = self._make_tool()
        create_result = await tool._arun(action="create", description="Goal A")
        goal_id = create_result["created"]["id"]
        await tool._arun(action="complete", goal_id=goal_id)

        pending = await tool._arun(action="list", status="pending")
        assert len(pending["goals"]) == 0
        completed = await tool._arun(action="list", status="completed")
        assert len(completed["goals"]) == 1

    @pytest.mark.asyncio
    async def test_complete_action(self):
        tool = self._make_tool()
        create_result = await tool._arun(action="create", description="To complete")
        goal_id = create_result["created"]["id"]
        result = await tool._arun(action="complete", goal_id=goal_id)
        assert result["completed"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_not_found(self):
        tool = self._make_tool()
        result = await tool._arun(action="complete", goal_id="nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fail_action(self):
        tool = self._make_tool()
        create_result = await tool._arun(action="create", description="To fail")
        goal_id = create_result["created"]["id"]
        result = await tool._arun(action="fail", goal_id=goal_id, error="test error")
        # With max_retries=2, first failure retries
        assert result["failed"]["status"] == "pending"
        assert result["failed"]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        tool = self._make_tool()
        result = await tool._arun(action="unknown_action")
        assert "error" in result

    def test_tool_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "manage_goals"
        assert "create" in tool.description
        assert "list" in tool.description
