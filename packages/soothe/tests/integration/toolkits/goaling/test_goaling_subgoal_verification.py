"""End-to-end verification for goaling tools subgoal creation (RFC-204 Group C).

This test demonstrates using suggest_goal to create a verification subgoal
that validates the tool integration works correctly. It exercises the full
flow from tool invocation through GoalDirective creation.

Scenario: An agent discovers it needs to verify tool integration before
proceeding with main task, so it creates a verification subgoal.
"""

from soothe.core.goal_engine.proposal_queue import Proposal, ProposalQueue
from soothe.core.runner._runner_autopilot_worker import _proposals_to_directives
from soothe.toolkits.goaling.add_finding import create_add_finding_tool
from soothe.toolkits.goaling.suggest_goal import create_suggest_goal_tool


class TestProposalToolSubgoalVerification:
    """Verify proposal tools can create verification subgoals.

    This test suite simulates an agent that:
    1. Discovers missing verification during main task execution
    2. Uses suggest_goal to create a verification subgoal
    3. Uses add_finding to record the discovery context
    4. Verifies the proposals convert to correct GoalDirectives
    """

    def test_create_verification_subgoal_via_tool(self) -> None:
        """Agent creates verification subgoal using suggest_goal tool.

        Scenario: Agent is executing "Test proposal tools" and discovers
        it should first verify the integration works correctly.
        """
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Agent discovers during execution that verification is needed
        result = tool._run(
            description="Verify suggest_goal tool integration with GoalDirective flow",
            priority=85,  # Higher priority than main task
            rationale="Integration tests must pass before main task proceeds",
        )

        # Tool confirms successful enqueue
        assert "Suggested goal queued" in result
        assert "priority=85" in result

        # Verify proposal in queue
        proposals = queue.drain()
        assert len(proposals) == 1

        p = proposals[0]
        assert p.type == "suggest_goal"
        assert p.goal_id == ""  # Will be filled by runner
        assert "Verify suggest_goal tool integration" in p.payload["description"]
        assert p.payload["priority"] == 85

    def test_proposal_converts_to_directive_with_correct_fields(self) -> None:
        """Verification subgoal converts to GoalDirective with correct fields."""
        queue = ProposalQueue()

        # Simulate tool creating verification subgoal
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={
                    "description": "Run pytest on proposal tool integration tests",
                    "priority": 90,
                    "depends_on": [],
                    "rationale": "Must verify tool-chain before proceeding",
                },
            )
        )

        # Convert to directives (as runner does)
        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="goal_main_001")

        assert len(directives) == 1
        d = directives[0]

        # Verify GoalDirective fields
        assert d.action == "create"
        assert d.description == "Run pytest on proposal tool integration tests"
        assert d.priority == 90
        assert d.parent_id is None  # Defaults to source_goal_id in apply_directives
        assert d.depends_on == []
        assert d.rationale == "Must verify tool-chain before proceeding"

    def test_multiple_verification_subgoals_with_dependencies(self) -> None:
        """Agent creates multiple verification subgoals with dependency chain.

        Scenario: Main task "Refactor proposal tools" requires:
        1. Verify current tests pass (no deps)
        2. Verify integration tests pass (depends on 1)
        3. Run full test suite (depends on 2)
        """
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # First verification subgoal (no dependencies)
        tool._run(
            description="Verify unit tests for proposal tools pass",
            priority=80,
            rationale="Baseline verification before refactor",
        )

        # Second verification subgoal (depends on first)
        tool._run(
            description="Verify integration tests for proposal tools pass",
            priority=85,
            depends_on=["goal_verify_unit"],
            rationale="Integration tests require passing unit tests",
        )

        # Third verification subgoal (depends on second)
        tool._run(
            description="Run full test suite with coverage",
            priority=75,
            depends_on=["goal_verify_integration"],
            rationale="Full suite requires all other tests passing",
        )

        # Convert all proposals to directives
        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="goal_refactor_main")

        assert len(directives) == 3

        # Verify dependency chain
        assert directives[0].description == "Verify unit tests for proposal tools pass"
        assert directives[0].depends_on == []

        assert directives[1].description == "Verify integration tests for proposal tools pass"
        assert directives[1].depends_on == ["goal_verify_unit"]

        assert directives[2].description == "Run full test suite with coverage"
        assert directives[2].depends_on == ["goal_verify_integration"]

    def test_add_finding_records_verification_context(self) -> None:
        """add_finding tool records context for verification subgoal.

        Scenario: Agent discovers missing test coverage and records finding
        for downstream verification subgoal to use.
        """
        queue = ProposalQueue()
        finding_tool = create_add_finding_tool(queue)

        result = finding_tool._run(
            summary="Found test_suggest_goal.py covers tool invocation but not queue drain semantics",
            relevance_score=0.85,
            tags=["verification", "coverage", "proposal-tools"],
        )

        # Tool confirms successful enqueue
        assert "Finding queued" in result
        assert "relevance=0.8" in result  # Displayed with 1 decimal

        # Verify proposal
        proposals = queue.drain()
        assert len(proposals) == 1

        p = proposals[0]
        assert p.type == "add_finding"
        assert "Found test_suggest_goal.py" in p.payload["summary"]
        assert p.payload["relevance_score"] == 0.85
        assert "verification" in p.payload["tags"]

    def test_mixed_proposals_only_suggest_goal_creates_directives(self) -> None:
        """Only suggest_goal creates directives; add_finding enriches context.

        This verifies the RFC-204 Group C design: suggest_goal creates
        GoalDirectives while add_finding flows through context_contribution.
        """
        queue = ProposalQueue()
        suggest_tool = create_suggest_goal_tool(queue)
        finding_tool = create_add_finding_tool(queue)

        # Record finding about verification gap
        finding_tool._run(
            summary="Integration tests missing for queue drain semantics",
            relevance_score=0.9,
            tags=["gap", "testing"],
        )

        # Create verification subgoal based on finding
        suggest_tool._run(
            description="Add integration tests for proposal queue drain",
            priority=70,
            rationale="Found missing test coverage for queue drain",
        )

        # Record another finding
        finding_tool._run(
            summary="test_proposals_to_directives covers conversion logic",
            relevance_score=0.7,
            tags=["existing-coverage"],
        )

        # Convert proposals
        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="goal_test_main")

        # Only suggest_goal creates directives
        assert len(directives) == 1
        assert directives[0].description == "Add integration tests for proposal queue drain"

        # add_finding proposals are preserved but don't become directives
        finding_proposals = [p for p in proposals if p.type == "add_finding"]
        assert len(finding_proposals) == 2

    def test_verification_subgoal_with_high_priority(self) -> None:
        """High-priority verification subgoal gets correct priority value.

        When verification is critical, agent sets high priority (90-100)
        to ensure it's scheduled before other work.
        """
        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Critical verification subgoal
        result = tool._run(
            description="CRITICAL: Verify proposal queue is not corrupted before proceeding",
            priority=95,
            rationale="Data integrity check required before state modification",
        )

        assert "priority=95" in result

        proposals = queue.drain()
        directives = _proposals_to_directives(proposals, source_goal_id="goal_main")

        assert directives[0].priority == 95

    def test_async_tool_invocation_matches_sync(self) -> None:
        """Async tool invocation produces same results as sync."""
        import asyncio

        queue = ProposalQueue()
        tool = create_suggest_goal_tool(queue)

        # Sync invocation
        sync_result = tool._run(
            description="Verify async tool parity",
            priority=50,
        )

        # Async invocation
        async def run_async() -> str:
            return await tool._arun(
                description="Verify async tool parity",
                priority=50,
            )

        async_result = asyncio.run(run_async())

        assert sync_result == async_result

        # Both should produce identical queue state
        proposals = queue.drain()
        assert len(proposals) == 2
        assert proposals[0].payload == proposals[1].payload


class TestGoalDirectiveSchemaValidation:
    """Validate GoalDirective schema matches proposal tool outputs."""

    def test_directive_action_is_create(self) -> None:
        """suggest_goal always creates 'create' action directives."""
        queue = ProposalQueue()
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={"description": "Test directive action"},
            )
        )

        directives = _proposals_to_directives(queue.drain(), source_goal_id="g1")

        assert len(directives) == 1
        assert directives[0].action == "create"

    def test_directive_priority_clamped_to_bounds(self) -> None:
        """Priority values are validated by GoalDirective schema."""
        # GoalDirective should accept values 0-100
        # Note: Clamping happens at tool level, not conversion level
        queue = ProposalQueue()

        # Valid priorities
        for priority in [0, 50, 100]:
            queue.enqueue(
                Proposal(
                    type="suggest_goal",
                    goal_id="",
                    payload={"description": f"Priority {priority}", "priority": priority},
                )
            )

        directives = _proposals_to_directives(queue.drain(), source_goal_id="g1")

        assert len(directives) == 3
        assert directives[0].priority == 0
        assert directives[1].priority == 50
        assert directives[2].priority == 100

    def test_directive_parent_id_defaults_to_source(self) -> None:
        """parent_id is None in directive; filled by apply_directives.

        The conversion doesn't set parent_id because the daemon's
        apply_directives uses source_goal_id as the parent.
        """
        queue = ProposalQueue()
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={"description": "Test parent ID"},
            )
        )

        directives = _proposals_to_directives(
            proposals=queue.drain(),
            source_goal_id="goal_parent_123",
        )

        assert directives[0].parent_id is None
        # Parent is set by apply_directives on daemon side using source_goal_id


class TestProposalQueueDrainSemantics:
    """Verify ProposalQueue drain behavior for verification scenarios."""

    def test_drain_returns_all_and_clears(self) -> None:
        """Drain returns all proposals and clears the queue."""
        queue = ProposalQueue()

        # Add multiple proposals
        queue.enqueue(Proposal(type="suggest_goal", goal_id="", payload={"description": "A"}))
        queue.enqueue(Proposal(type="suggest_goal", goal_id="", payload={"description": "B"}))
        queue.enqueue(Proposal(type="suggest_goal", goal_id="", payload={"description": "C"}))

        # Drain returns all
        proposals = queue.drain()
        assert len(proposals) == 3

        # Queue is now empty
        assert queue.is_empty()
        assert queue.drain() == []

    def test_proposal_timestamp_auto_generated(self) -> None:
        """Proposals get UTC timestamp on creation."""
        from datetime import UTC, datetime

        queue = ProposalQueue()
        before = datetime.now(tz=UTC)

        queue.enqueue(Proposal(type="suggest_goal", goal_id="", payload={}))

        after = datetime.now(tz=UTC)
        proposals = queue.drain()

        assert before <= proposals[0].timestamp <= after
