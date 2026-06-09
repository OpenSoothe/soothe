"""Integration verification for suggest_goal tool (RFC-204 Group C).

This test verifies the complete flow:
    suggest_goal tool → ProposalQueue → GoalDirective conversion

It demonstrates the proactive subgoal creation mechanism that allows
Layer 2 (AgentLoop) to suggest new subgoals during execution.
"""

import pytest

from soothe.foundation.autopilot.engine.proposal_queue import Proposal, ProposalQueue
from soothe.runner._runner_autopilot_worker import _proposals_to_directives
from soothe.toolkits.goaling.suggest_goal import SuggestGoalTool, create_suggest_goal_tool


class TestSuggestGoalIntegration:
    """Verify suggest_goal tool integration with proposal queue."""

    def test_tool_to_queue_integration(self) -> None:
        """suggest_goal tool correctly enqueues to ProposalQueue."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Simulate agent using the tool during execution
        result = tool._run(
            description="Verify test coverage for proposal tools",
            priority=75,
            rationale="Found missing test cases during exploration",
        )

        # Verify tool response
        assert "Suggested goal queued" in result
        assert "priority=75" in result

        # Verify queue state
        assert not queue.is_empty()
        proposals = queue.drain()
        assert len(proposals) == 1

        proposal = proposals[0]
        assert proposal.type == "suggest_goal"
        assert proposal.payload["description"] == "Verify test coverage for proposal tools"
        assert proposal.payload["priority"] == 75
        assert proposal.payload["rationale"] == "Found missing test cases during exploration"

    def test_queue_to_directive_conversion(self) -> None:
        """ProposalQueue proposals convert to GoalDirectives."""
        queue = ProposalQueue()

        # Enqueue multiple suggestions (simulating tool usage)
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={
                    "description": "Create integration tests",
                    "priority": 80,
                    "depends_on": [],
                    "rationale": "Need test coverage",
                },
            )
        )
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={
                    "description": "Update documentation",
                    "priority": 60,
                    "depends_on": ["goal_001"],
                    "rationale": "Reflect new API",
                },
            )
        )

        # Convert proposals to directives (as done by runner)
        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="parent_goal_123")

        assert len(directives) == 2

        # First directive
        d1 = directives[0]
        assert d1.action == "create"
        assert d1.description == "Create integration tests"
        assert d1.priority == 80
        assert d1.rationale == "Need test coverage"

        # Second directive
        d2 = directives[1]
        assert d2.action == "create"
        assert d2.description == "Update documentation"
        assert d2.priority == 60
        assert d2.depends_on == ["goal_001"]

    def test_full_flow_multiple_tools(self) -> None:
        """Multiple suggest_goal calls queue and convert correctly."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Simulate agent discovering multiple subgoals during execution
        tool._run(description="Install missing dependency", priority=90, rationale="Build fails")
        tool._run(description="Fix import paths", priority=85, depends_on=["dep_fix"])
        tool._run(description="Run linting checks", priority=70)

        # Convert all queued proposals
        proposals = queue.drain()
        assert len(proposals) == 3

        directives = _proposals_to_directives(proposals, source_goal_id="main_goal")

        # Verify all converted
        assert len(directives) == 3
        assert directives[0].description == "Install missing dependency"
        assert directives[0].priority == 90
        assert directives[1].description == "Fix import paths"
        assert directives[1].depends_on == ["dep_fix"]
        assert directives[2].description == "Run linting checks"
        assert directives[2].priority == 70

    def test_tool_without_queue_returns_error(self) -> None:
        """Tool returns error message when queue is not configured."""
        tool = SuggestGoalTool()  # No queue injected

        result = tool._run(description="This should fail")

        assert "Error" in result
        assert "proposal_queue" in result.lower()

    def test_dependency_chain_creation(self) -> None:
        """suggest_goal can express dependency chains."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Create a chain of dependencies
        tool._run(
            description="Setup database schema",
            priority=80,
            rationale="Prerequisite for migrations",
        )
        tool._run(
            description="Run database migrations",
            priority=75,
            depends_on=["schema_setup"],
            rationale="Needs schema first",
        )
        tool._run(
            description="Seed test data",
            priority=70,
            depends_on=["migrations"],
            rationale="Needs migrated schema",
        )

        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="db_init")

        assert len(directives) == 3
        assert directives[0].depends_on == []  # No dependencies
        assert directives[1].depends_on == ["schema_setup"]
        assert directives[2].depends_on == ["migrations"]

    @pytest.mark.asyncio
    async def test_async_integration_same_as_sync(self) -> None:
        """Async tool execution produces same results as sync."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        result = await tool._arun(
            description="Async subgoal verification",
            priority=65,
            rationale="Testing async path",
        )

        assert "queued" in result.lower()

        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].type == "suggest_goal"
        assert proposals[0].payload["description"] == "Async subgoal verification"


class TestProposalQueueDrainSemantics:
    """Verify ProposalQueue drain behavior for tool integration."""

    def test_drain_empties_queue(self) -> None:
        """After drain, queue is empty."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        tool._run(description="Task 1")
        tool._run(description="Task 2")

        assert not queue.is_empty()
        first_drain = queue.drain()
        assert len(first_drain) == 2
        assert queue.is_empty()

        # Second drain returns empty
        second_drain = queue.drain()
        assert len(second_drain) == 0

    def test_proposals_have_timestamps(self) -> None:
        """Proposals include timestamp metadata."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        tool._run(description="Timestamped task")

        proposals = queue.drain()
        assert len(proposals) == 1
        assert proposals[0].timestamp is not None


class TestGoalDirectiveSchema:
    """Verify GoalDirectives produced from suggest_goal have correct schema."""

    def test_directive_action_is_create(self) -> None:
        """suggest_goal always produces 'create' action directives."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        tool._run(description="New task")

        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="parent")

        assert directives[0].action == "create"

    def test_directive_priority_bounds(self) -> None:
        """Priority values are bounded 0-100 per tool schema."""
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Test various priorities
        for priority in [0, 50, 100]:
            tool._run(description=f"Task with priority {priority}", priority=priority)

        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="parent")

        assert directives[0].priority == 0
        assert directives[1].priority == 50
        assert directives[2].priority == 100

    def test_directive_default_priority(self) -> None:
        """Default priority is 50 when not specified."""
        proposals = [
            Proposal(
                type="suggest_goal", goal_id="", payload={"description": "Default priority task"}
            )
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="parent")

        assert directives[0].priority == 50
