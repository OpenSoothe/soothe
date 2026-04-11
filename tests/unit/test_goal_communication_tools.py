"""Tests for goal-to-manager communication tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition import Goal, GoalEngine
from soothe.cognition.goal_engine.proposal_queue import ProposalQueue
from soothe.tools.goals.implementation import (
    AddFindingTool,
    FlagBlockerTool,
    GetGoalProgressTool,
    GetRelatedGoalsTool,
    GetWorldInfoTool,
    ReportProgressTool,
    SearchMemoryTool,
    SuggestGoalTool,
    create_agent_loop_tools,
)


def _make_goal(description: str, status: str = "pending") -> Goal:
    """Helper to create a Goal with known ID."""
    return Goal(description=description, status=status)


class TestGetRelatedGoalsTool:
    """Tests for GetRelatedGoalsTool."""

    @pytest.mark.asyncio
    async def test_finds_matching_goals(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Update homepage CSS")
        await engine.create_goal("Write documentation")
        g3 = await engine.create_goal("Fix database connection")
        engine._goals[g3.id].status = "active"

        tool = GetRelatedGoalsTool(goal_engine=engine)
        result = await tool._arun(query="Fix database")
        assert "related_goals" in result
        assert len(result["related_goals"]) == 1
        assert result["related_goals"][0]["description"] == "Fix database connection"

    @pytest.mark.asyncio
    async def test_empty_result_no_match(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Fix login bug")

        tool = GetRelatedGoalsTool(goal_engine=engine)
        result = await tool._arun(query="unrelated topic xyz")
        assert result["related_goals"] == []

    @pytest.mark.asyncio
    async def test_empty_query_error(self) -> None:
        engine = GoalEngine()
        tool = GetRelatedGoalsTool(goal_engine=engine)
        result = tool._run(query="")
        assert "error" in result
        assert "query is required" in result["error"]

    @pytest.mark.asyncio
    async def test_only_active_completed_validated(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Active task")
        g2 = await engine.create_goal("Completed task")
        g3 = await engine.create_goal("Pending task")
        g4 = await engine.create_goal("Failed task")
        engine._goals[g1.id].status = "active"
        engine._goals[g2.id].status = "completed"
        engine._goals[g3.id].status = "pending"
        engine._goals[g4.id].status = "failed"

        tool = GetRelatedGoalsTool(goal_engine=engine)
        result = await tool._arun(query="task")
        assert len(result["related_goals"]) == 2
        statuses = {g["status"] for g in result["related_goals"]}
        assert "pending" not in statuses
        assert "failed" not in statuses


class TestGetGoalProgressTool:
    """Tests for GetGoalProgressTool."""

    @pytest.mark.asyncio
    async def test_returns_goal_details(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("My task", priority=75)

        tool = GetGoalProgressTool(goal_engine=engine)
        result = await tool._arun(goal_id=goal.id)
        assert result["goal_id"] == goal.id
        assert result["description"] == "My task"
        assert result["status"] == "pending"
        assert result["priority"] == 75

    @pytest.mark.asyncio
    async def test_error_nonexistent_goal(self) -> None:
        engine = GoalEngine()
        tool = GetGoalProgressTool(goal_engine=engine)
        result = await tool._arun(goal_id="nonexistent")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        engine = GoalEngine()
        tool = GetGoalProgressTool(goal_engine=engine)
        result = tool._run(goal_id="")
        assert "error" in result
        assert "goal_id is required" in result["error"]


class TestReportProgressTool:
    """Tests for ReportProgressTool."""

    @pytest.mark.asyncio
    async def test_enqueues_proposal(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Work in progress")

        tool = ReportProgressTool(goal_engine=engine)
        result = await tool._arun(goal_id=goal.id, status="in_progress", findings="Made good progress")
        assert result["status"] == "queued"
        assert result["goal_id"] == goal.id

    @pytest.mark.asyncio
    async def test_error_nonexistent_goal(self) -> None:
        engine = GoalEngine()
        tool = ReportProgressTool(goal_engine=engine)
        result = await tool._arun(goal_id="nonexistent", status="ok")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        engine = GoalEngine()
        tool = ReportProgressTool(goal_engine=engine)
        result = tool._run(goal_id="")
        assert "error" in result
        assert "goal_id is required" in result["error"]


class TestSuggestGoalTool:
    """Tests for SuggestGoalTool."""

    @pytest.mark.asyncio
    async def test_enqueues_proposal(self) -> None:
        engine = GoalEngine()
        tool = SuggestGoalTool(goal_engine=engine)
        result = await tool._arun(description="New goal idea", priority=80)
        assert result["status"] == "proposed"
        assert result["description"] == "New goal idea"
        assert result["priority"] == 80

    @pytest.mark.asyncio
    async def test_default_priority(self) -> None:
        engine = GoalEngine()
        tool = SuggestGoalTool(goal_engine=engine)
        result = await tool._arun(description="Simple goal")
        assert result["priority"] == 50

    @pytest.mark.asyncio
    async def test_empty_description_error(self) -> None:
        engine = GoalEngine()
        tool = SuggestGoalTool(goal_engine=engine)
        result = tool._run(description="")
        assert "error" in result
        assert "description is required" in result["error"]


class TestFlagBlockerTool:
    """Tests for FlagBlockerTool."""

    @pytest.mark.asyncio
    async def test_enqueues_proposal_with_reason(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Blocked task")

        tool = FlagBlockerTool(goal_engine=engine)
        result = await tool._arun(goal_id=goal.id, reason="API is down")
        assert result["status"] == "flagged"
        assert result["goal_id"] == goal.id
        assert result["reason"] == "API is down"

    @pytest.mark.asyncio
    async def test_with_dependencies(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Blocked by deps")

        tool = FlagBlockerTool(goal_engine=engine)
        result = await tool._arun(goal_id=goal.id, reason="waiting", dependencies="subgoal-123")
        assert result["status"] == "flagged"

    @pytest.mark.asyncio
    async def test_error_missing_reason(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Task")

        tool = FlagBlockerTool(goal_engine=engine)
        result = await tool._arun(goal_id=goal.id, reason="")
        assert "error" in result
        assert "reason is required" in result["error"]

    @pytest.mark.asyncio
    async def test_error_missing_goal_id(self) -> None:
        engine = GoalEngine()
        tool = FlagBlockerTool(goal_engine=engine)
        result = tool._run(goal_id="", reason="blocked")
        assert "error" in result
        assert "goal_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_error_nonexistent_goal(self) -> None:
        engine = GoalEngine()
        tool = FlagBlockerTool(goal_engine=engine)
        result = await tool._arun(goal_id="nonexistent", reason="blocked")
        assert "error" in result
        assert "not found" in result["error"]


class TestGetWorldInfoTool:
    """Tests for GetWorldInfoTool."""

    @pytest.mark.asyncio
    async def test_returns_active_goal_count(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Active 1")
        g2 = await engine.create_goal("Active 2")
        await engine.create_goal("Pending 1")
        engine._goals[g1.id].status = "active"
        engine._goals[g2.id].status = "active"

        tool = GetWorldInfoTool(
            goal_engine=engine,
            iteration_count=5,
            workspace="/tmp/workspace",
            available_subagents=["browser", "claude"],
        )
        result = await tool._arun()
        assert result["active_goals"] == 2
        assert result["total_goals"] == 3
        assert result["iteration_count"] == 5
        assert result["workspace"] == "/tmp/workspace"
        assert result["available_subagents"] == ["browser", "claude"]

    @pytest.mark.asyncio
    async def test_empty_state(self) -> None:
        engine = GoalEngine()
        tool = GetWorldInfoTool(
            goal_engine=engine,
            iteration_count=0,
            workspace="/tmp/test",
            available_subagents=[],
        )
        result = await tool._arun()
        assert result["active_goals"] == 0
        assert result["total_goals"] == 0
        assert result["iteration_count"] == 0


class TestSearchMemoryTool:
    """Tests for SearchMemoryTool."""

    @pytest.mark.asyncio
    async def test_searches_memory(self) -> None:
        memory = AsyncMock()
        memory.recall.return_value = [
            {"text": "Found item 1"},
            {"text": "Found item 2"},
        ]

        tool = SearchMemoryTool(memory_protocol=memory)
        result = await tool._arun(query="test query", limit=3)
        memory.recall.assert_called_once_with("test query", limit=3)
        assert "results" in result
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_handles_memory_errors(self) -> None:
        memory = AsyncMock()
        memory.recall.side_effect = Exception("Connection failed")

        tool = SearchMemoryTool(memory_protocol=memory)
        result = await tool._arun(query="test")
        assert "error" in result
        assert "Memory search failed" in result["error"]

    @pytest.mark.asyncio
    async def test_requires_query(self) -> None:
        memory = AsyncMock()
        tool = SearchMemoryTool(memory_protocol=memory)
        result = tool._run(query="")
        assert "error" in result
        assert "query is required" in result["error"]

    @pytest.mark.asyncio
    async def test_default_limit(self) -> None:
        memory = AsyncMock()
        memory.recall.return_value = []
        tool = SearchMemoryTool(memory_protocol=memory)
        await tool._arun(query="test")
        memory.recall.assert_called_once_with("test", limit=5)


class TestAddFindingTool:
    """Tests for AddFindingTool."""

    @pytest.mark.asyncio
    async def test_enqueues_finding(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Research task")
        queue = ProposalQueue()

        tool = AddFindingTool(goal_engine=engine, proposal_queue=queue)
        result = await tool._arun(goal_id=goal.id, content="Important finding", tags="research,data")
        assert result["status"] == "queued"
        assert result["goal_id"] == goal.id
        assert result["content_preview"] == "Important finding"

        # Verify proposal was enqueued
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "add_finding"
        assert proposals[0].goal_id == goal.id
        assert proposals[0].payload["content"] == "Important finding"
        assert proposals[0].payload["tags"] == ["research", "data"]

    @pytest.mark.asyncio
    async def test_enqueues_without_tags(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Task")
        queue = ProposalQueue()

        tool = AddFindingTool(goal_engine=engine, proposal_queue=queue)
        await tool._arun(goal_id=goal.id, content="No tags finding", tags="")

        proposals = queue.drain()
        assert proposals[0].payload["tags"] == []

    @pytest.mark.asyncio
    async def test_error_missing_goal_id(self) -> None:
        engine = GoalEngine()
        queue = ProposalQueue()
        tool = AddFindingTool(goal_engine=engine, proposal_queue=queue)
        result = tool._run(goal_id="", content="test")
        assert "error" in result
        assert "goal_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_error_missing_content(self) -> None:
        engine = GoalEngine()
        queue = ProposalQueue()
        tool = AddFindingTool(goal_engine=engine, proposal_queue=queue)
        result = tool._run(goal_id="some-id", content="")
        assert "error" in result
        assert "content is required" in result["error"]

    @pytest.mark.asyncio
    async def test_error_nonexistent_goal(self) -> None:
        engine = GoalEngine()
        queue = ProposalQueue()
        tool = AddFindingTool(goal_engine=engine, proposal_queue=queue)
        result = await tool._arun(goal_id="nonexistent", content="test")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_queue_no_crash(self) -> None:
        """Tool should work even with no proposal_queue (queue is optional)."""
        engine = GoalEngine()
        goal = await engine.create_goal("Task")
        tool = AddFindingTool(goal_engine=engine, proposal_queue=None)
        result = await tool._arun(goal_id=goal.id, content="Finding")
        assert result["status"] == "queued"


class TestCreateAgentLoopTools:
    """Tests for create_agent_loop_tools() factory function."""

    def test_returns_all_tools_with_full_params(self) -> None:
        engine = GoalEngine()
        queue = ProposalQueue()
        memory = MagicMock()

        tools = create_agent_loop_tools(
            goal_engine=engine,
            proposal_queue=queue,
            memory_protocol=memory,
            iteration_count=10,
            workspace="/tmp/ws",
            available_subagents=["browser", "claude"],
        )

        tool_names = {t.name for t in tools}
        expected = {
            "get_related_goals",
            "get_goal_progress",
            "report_progress",
            "suggest_goal",
            "flag_blocker",
            "get_world_info",
            "search_memory",
            "add_finding",
        }
        assert tool_names == expected

        # Verify GetWorldInfoTool was configured with params
        world_info = next(t for t in tools if t.name == "get_world_info")
        assert world_info.iteration_count == 10
        assert world_info.workspace == "/tmp/ws"
        assert world_info.available_subagents == ["browser", "claude"]

        # Verify SearchMemoryTool was included
        search_tool = next(t for t in tools if t.name == "search_memory")
        assert search_tool.memory_protocol is memory

        # Verify AddFindingTool has queue
        finding_tool = next(t for t in tools if t.name == "add_finding")
        assert finding_tool.proposal_queue is queue

    def test_works_with_minimal_params(self) -> None:
        """Backward compat: only goal_engine is required."""
        engine = GoalEngine()

        tools = create_agent_loop_tools(goal_engine=engine)

        tool_names = {t.name for t in tools}
        expected = {
            "get_related_goals",
            "get_goal_progress",
            "report_progress",
            "suggest_goal",
            "flag_blocker",
            "get_world_info",
            "add_finding",
        }
        # search_memory is NOT included without memory_protocol
        assert tool_names == expected

    def test_includes_search_memory_only_with_protocol(self) -> None:
        engine = GoalEngine()
        memory = MagicMock()

        tools = create_agent_loop_tools(goal_engine=engine, memory_protocol=memory)
        tool_names = {t.name for t in tools}
        assert "search_memory" in tool_names
