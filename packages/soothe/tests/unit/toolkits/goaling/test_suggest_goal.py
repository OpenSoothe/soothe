"""Tests for suggest_goal tool (RFC-204 Group C)."""

import pytest

from soothe.core.goal_engine.proposal_queue import ProposalQueue
from soothe.toolkits.goaling.suggest_goal import SuggestGoalTool, create_suggest_goal_tool


class TestSuggestGoalTool:
    """Test suggest_goal tool functionality."""

    def test_tool_name_and_description(self) -> None:
        """Tool has correct name and description."""
        tool = SuggestGoalTool()
        assert tool.name == "suggest_goal"
        assert "subgoal" in tool.description.lower()

    def test_enqueue_without_queue_returns_error(self) -> None:
        """Without proposal_queue, tool returns error message."""
        tool = SuggestGoalTool()
        result = tool._run(description="test goal")
        assert "Error" in result
        assert "proposal_queue" in result.lower()

    def test_enqueue_basic_proposal(self) -> None:
        """Basic suggest_goal enqueueing."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        result = tool._run(description="Analyze dataset", priority=80)

        assert "Suggested goal queued" in result
        assert "priority=80" in result

        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "suggest_goal"
        assert proposals[0].payload["description"] == "Analyze dataset"
        assert proposals[0].payload["priority"] == 80

    def test_enqueue_with_full_parameters(self) -> None:
        """suggest_goal with all parameters."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        result = tool._run(
            description="Install missing dependency",
            priority=90,
            depends_on=["goal_001", "goal_002"],
            rationale="Cannot proceed without this library",
        )

        assert "queued" in result.lower()

        proposals = queue.drain()
        assert len(proposals) == 1
        p = proposals[0]
        assert p.payload["description"] == "Install missing dependency"
        assert p.payload["priority"] == 90
        assert p.payload["depends_on"] == ["goal_001", "goal_002"]
        assert p.payload["rationale"] == "Cannot proceed without this library"

    def test_default_priority_is_50(self) -> None:
        """Default priority is 50."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        tool._run(description="test")

        proposals = queue.drain()
        assert proposals[0].payload["priority"] == 50

    def test_multiple_suggestions_queue_sequentially(self) -> None:
        """Multiple suggestions enqueue in order."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        tool._run(description="First suggestion", priority=60)
        tool._run(description="Second suggestion", priority=70)
        tool._run(description="Third suggestion", priority=80)

        proposals = queue.drain()
        assert len(proposals) == 3
        assert proposals[0].payload["description"] == "First suggestion"
        assert proposals[1].payload["description"] == "Second suggestion"
        assert proposals[2].payload["description"] == "Third suggestion"

    @pytest.mark.asyncio
    async def test_async_run_same_as_sync(self) -> None:
        """Async variant works identically."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        result = await tool._arun(description="async test", priority=55)

        assert "queued" in result.lower()
        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].payload["priority"] == 55

    def test_truncates_long_description_in_output(self) -> None:
        """Long description is truncated in output message."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        long_desc = "This is a very long goal description that should be truncated in the output message for readability"
        result = tool._run(description=long_desc)

        # Output should contain truncated preview
        assert "..." in result or len(result) < len(long_desc) + 50

        # But payload should have full description
        proposals = queue.drain()
        assert proposals[0].payload["description"] == long_desc
