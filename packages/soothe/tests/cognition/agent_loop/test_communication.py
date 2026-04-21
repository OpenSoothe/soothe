"""Tests for GoalCommunicationHelper (RFC-204 Layer 2 ↔ Layer 3 communication)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition import Goal, GoalEngine
from soothe.cognition.agent_loop.communication import GoalCommunicationHelper
from soothe.cognition.goal_engine.proposal_queue import ProposalQueue


def _make_goal(description: str, status: str = "pending") -> Goal:
    """Helper to create a Goal with known ID."""
    return Goal(description=description, status=status)


class TestGetRelatedGoals:
    """Tests for get_related_goals query operation."""

    @pytest.mark.asyncio
    async def test_finds_matching_goals(self) -> None:
        """Should find goals matching query."""
        engine = GoalEngine()
        await engine.create_goal("Update homepage CSS")
        await engine.create_goal("Write documentation")
        g3 = await engine.create_goal("Fix database connection")
        engine._goals[g3.id].status = "active"

        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_related_goals(query="Fix database")
        assert "related_goals" in result
        assert len(result["related_goals"]) == 1
        assert result["related_goals"][0]["description"] == "Fix database connection"

    @pytest.mark.asyncio
    async def test_empty_result_no_match(self) -> None:
        """Should return empty list if no matches."""
        engine = GoalEngine()
        await engine.create_goal("Fix login bug")

        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_related_goals(query="unrelated topic xyz")
        assert result["related_goals"] == []

    @pytest.mark.asyncio
    async def test_empty_query_error(self) -> None:
        """Should return error for empty query."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_related_goals(query="")
        assert "error" in result
        assert "query is required" in result["error"]

    @pytest.mark.asyncio
    async def test_only_active_completed_validated(self) -> None:
        """Should only return active/completed/validated goals."""
        engine = GoalEngine()
        g1 = await engine.create_goal("Active task")
        g2 = await engine.create_goal("Completed task")
        g3 = await engine.create_goal("Pending task")
        g4 = await engine.create_goal("Failed task")
        engine._goals[g1.id].status = "active"
        engine._goals[g2.id].status = "completed"
        engine._goals[g3.id].status = "pending"
        engine._goals[g4.id].status = "failed"

        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_related_goals(query="task")
        assert len(result["related_goals"]) == 2
        statuses = {g["status"] for g in result["related_goals"]}
        assert "pending" not in statuses
        assert "failed" not in statuses


class TestGetGoalProgress:
    """Tests for get_goal_progress query operation."""

    @pytest.mark.asyncio
    async def test_returns_goal_details(self) -> None:
        """Should return goal ID, description, status, priority."""
        engine = GoalEngine()
        goal = await engine.create_goal("My task", priority=75)

        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_goal_progress(goal_id=goal.id)
        assert result["goal_id"] == goal.id
        assert result["description"] == "My task"
        assert result["status"] == "pending"
        assert result["priority"] == 75

    @pytest.mark.asyncio
    async def test_error_nonexistent_goal(self) -> None:
        """Should return error for nonexistent goal."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_goal_progress(goal_id="nonexistent")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        """Should return error for empty goal_id."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.get_goal_progress(goal_id="")
        assert "error" in result
        assert "goal_id is required" in result["error"]


class TestGetWorldInfo:
    """Tests for get_world_info query operation."""

    @pytest.mark.asyncio
    async def test_returns_world_state(self) -> None:
        """Should return iteration_count, workspace, active_goals."""
        engine = GoalEngine()
        await engine.create_goal("Task A")
        g2 = await engine.create_goal("Task B")
        engine._goals[g2.id].status = "active"

        helper = GoalCommunicationHelper(
            goal_engine=engine,
            iteration_count=5,
            workspace="/tmp/test",
            available_subagents=["browser", "research"],
        )
        result = await helper.get_world_info()
        assert result["active_goals"] == 1
        assert result["total_goals"] == 2
        assert result["iteration_count"] == 5
        assert result["workspace"] == "/tmp/test"
        assert result["available_subagents"] == ["browser", "research"]

    @pytest.mark.asyncio
    async def test_empty_subagents_list(self) -> None:
        """Should handle empty subagents list."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(
            goal_engine=engine,
            available_subagents=None,
        )
        result = await helper.get_world_info()
        assert result["available_subagents"] == []


class TestSearchMemory:
    """Tests for search_memory query operation."""

    @pytest.mark.asyncio
    async def test_returns_memory_results(self) -> None:
        """Should return memory protocol results."""
        engine = GoalEngine()
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=["item1", "item2"])

        helper = GoalCommunicationHelper(goal_engine=engine, memory_protocol=memory)
        result = await helper.search_memory(query="test query", limit=3)
        assert "results" in result
        assert len(result["results"]) == 2
        memory.recall.assert_called_once_with("test query", limit=3)

    @pytest.mark.asyncio
    async def test_empty_query_error(self) -> None:
        """Should return error for empty query."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.search_memory(query="")
        assert "error" in result
        assert "query is required" in result["error"]

    @pytest.mark.asyncio
    async def test_no_memory_protocol_error(self) -> None:
        """Should return error if memory protocol not available."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine, memory_protocol=None)
        result = await helper.search_memory(query="test")
        assert "error" in result
        assert "Memory protocol not available" in result["error"]

    @pytest.mark.asyncio
    async def test_handles_memory_search_exception(self) -> None:
        """Should handle memory search exceptions."""
        engine = GoalEngine()
        memory = AsyncMock()
        memory.recall = AsyncMock(side_effect=Exception("Memory error"))

        helper = GoalCommunicationHelper(goal_engine=engine, memory_protocol=memory)
        result = await helper.search_memory(query="test")
        assert "error" in result
        assert "Memory search failed" in result["error"]


class TestReportProgress:
    """Tests for report_progress proposal operation."""

    @pytest.mark.asyncio
    async def test_queues_progress_update(self) -> None:
        """Should queue progress update in proposal queue."""
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal")
        queue = ProposalQueue()

        helper = GoalCommunicationHelper(goal_engine=engine, proposal_queue=queue)
        result = await helper.report_progress(
            goal_id=goal.id, status="working", findings="Found bug in module X"
        )

        assert result["status"] == "queued"
        assert result["goal_id"] == goal.id

        # Check queue
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "report_progress"
        assert proposals[0].goal_id == goal.id
        assert proposals[0].payload["status"] == "working"

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        """Should return error for empty goal_id."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.report_progress(goal_id="", status="working")
        assert "error" in result
        assert "goal_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_goal_error(self) -> None:
        """Should return error for nonexistent goal."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.report_progress(goal_id="nonexistent", status="working")
        assert "error" in result
        assert "not found" in result["error"]


class TestSuggestGoal:
    """Tests for suggest_goal proposal operation."""

    @pytest.mark.asyncio
    async def test_queues_goal_proposal(self) -> None:
        """Should queue goal proposal."""
        engine = GoalEngine()
        queue = ProposalQueue()

        helper = GoalCommunicationHelper(goal_engine=engine, proposal_queue=queue)
        result = await helper.suggest_goal(description="New goal proposal", priority=80)

        assert result["status"] == "proposed"
        assert result["description"] == "New goal proposal"
        assert result["priority"] == 80

        # Check queue
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "suggest_goal"
        assert proposals[0].payload["description"] == "New goal proposal"
        assert proposals[0].payload["priority"] == 80

    @pytest.mark.asyncio
    async def test_empty_description_error(self) -> None:
        """Should return error for empty description."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.suggest_goal(description="")
        assert "error" in result
        assert "description is required" in result["error"]


class TestFlagBlocker:
    """Tests for flag_blocker proposal operation."""

    @pytest.mark.asyncio
    async def test_queues_blocker_signal(self) -> None:
        """Should queue blocker signal."""
        engine = GoalEngine()
        goal = await engine.create_goal("Blocked goal")
        queue = ProposalQueue()

        helper = GoalCommunicationHelper(goal_engine=engine, proposal_queue=queue)
        result = await helper.flag_blocker(
            goal_id=goal.id, reason="Missing dependency", dependencies="goal_abc"
        )

        assert result["status"] == "flagged"
        assert result["goal_id"] == goal.id
        assert result["reason"] == "Missing dependency"

        # Check queue
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "flag_blocker"
        assert proposals[0].goal_id == goal.id
        assert proposals[0].payload["reason"] == "Missing dependency"

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        """Should return error for empty goal_id."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.flag_blocker(goal_id="", reason="test")
        assert "error" in result
        assert "goal_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_reason_error(self) -> None:
        """Should return error for empty reason."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.flag_blocker(goal_id="test", reason="")
        assert "error" in result
        assert "reason is required" in result["error"]


class TestAddFinding:
    """Tests for add_finding proposal operation."""

    @pytest.mark.asyncio
    async def test_queues_finding(self) -> None:
        """Should queue finding for goal."""
        engine = GoalEngine()
        goal = await engine.create_goal("Research goal")
        queue = ProposalQueue()

        helper = GoalCommunicationHelper(goal_engine=engine, proposal_queue=queue)
        result = await helper.add_finding(
            goal_id=goal.id,
            content="Discovered X affects Y",
            tags="research,important",
        )

        assert result["status"] == "queued"
        assert result["goal_id"] == goal.id
        assert "Discovered X affects Y" in result["content_preview"]

        # Check queue
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "add_finding"
        assert proposals[0].goal_id == goal.id
        assert proposals[0].payload["content"] == "Discovered X affects Y"
        assert proposals[0].payload["tags"] == ["research", "important"]

    @pytest.mark.asyncio
    async def test_empty_goal_id_error(self) -> None:
        """Should return error for empty goal_id."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.add_finding(goal_id="", content="test")
        assert "error" in result
        assert "goal_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_content_error(self) -> None:
        """Should return error for empty content."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.add_finding(goal_id="test", content="")
        assert "error" in result
        assert "content is required" in result["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_goal_error(self) -> None:
        """Should return error for nonexistent goal."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)
        result = await helper.add_finding(goal_id="nonexistent", content="test")
        assert "error" in result
        assert "not found" in result["error"]


class TestGoalCommunicationHelperFactory:
    """Tests for GoalCommunicationHelper initialization."""

    def test_initialization_with_all_params(self) -> None:
        """Should initialize with all parameters."""
        engine = GoalEngine()
        queue = ProposalQueue()
        memory = MagicMock()

        helper = GoalCommunicationHelper(
            goal_engine=engine,
            proposal_queue=queue,
            memory_protocol=memory,
            iteration_count=10,
            workspace="/test/path",
            available_subagents=["agent1", "agent2"],
        )

        assert helper._goal_engine == engine
        assert helper._proposal_queue == queue
        assert helper._memory_protocol == memory
        assert helper._iteration_count == 10
        assert helper._workspace == "/test/path"
        assert helper._available_subagents == ["agent1", "agent2"]

    def test_initialization_with_defaults(self) -> None:
        """Should initialize with default values."""
        engine = GoalEngine()
        helper = GoalCommunicationHelper(goal_engine=engine)

        assert helper._goal_engine == engine
        assert helper._proposal_queue is None
        assert helper._memory_protocol is None
        assert helper._iteration_count == 0
        assert helper._workspace == ""
        assert helper._available_subagents == []
