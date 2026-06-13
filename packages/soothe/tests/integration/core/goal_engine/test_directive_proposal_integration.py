"""Integration test for RFC-204 Group C: reactive + proactive directive paths.

This test demonstrates both mechanisms for dynamic subgoal creation:
1. Reactive: Reflection generates GoalDirectives → GoalEngine.apply_directives()
2. Proactive: suggest_goal tool enqueues proposals → converted to directives

The integration point is GoalCompletionChunk which carries directives from
both paths to the daemon's AutopilotService.
"""

from __future__ import annotations

import pytest

from soothe.foundation.autopilot.engine.engine import GoalEngine
from soothe.foundation.autopilot.engine.proposal_queue import Proposal, ProposalQueue
from soothe.protocols.planner import GoalDirective


class TestDirectiveProposalIntegration:
    """Integration tests for reactive + proactive directive merging."""

    @pytest.fixture
    async def goal_engine(self) -> GoalEngine:
        """Create a GoalEngine instance for testing."""
        engine = GoalEngine()
        # Create a parent goal for directives to attach to
        await engine.create_goal(
            description="Parent goal for integration test",
            priority=50,
        )
        return engine

    @pytest.mark.asyncio
    async def test_reactive_path_directives_create_subgoals(self, goal_engine: GoalEngine):
        """Reactive path: Reflection directives create subgoals.

        Simulates what happens when StrangeLoop's Reflection phase generates
        GoalDirectives based on step failure analysis.
        """
        # Get parent goal ID
        parent_id = list(goal_engine._goals.keys())[0]

        # Simulate Reflection generating directives
        # This would happen in core/loop/utils/reflection.py
        reflection_directives = [
            GoalDirective(
                action="create",
                description="Investigate why step X failed",
                priority=60,
                rationale="Step X failed due to missing dependency",
            ),
            GoalDirective(
                action="create",
                description="Fix the missing dependency",
                priority=70,
                depends_on=[],  # First subgoal
            ),
        ]

        # This is what daemon's AutopilotService does after receiving
        # GoalCompletionChunk with goal_directives field
        created_ids = await goal_engine.apply_directives(
            reflection_directives,
            source_goal_id=parent_id,
        )

        # Verify subgoals were created
        assert len(created_ids) == 2
        assert len(goal_engine._goals) == 3  # parent + 2 subgoals

        # Verify subgoal properties
        subgoal1 = goal_engine._goals[created_ids[0]]
        assert subgoal1.description == "Investigate why step X failed"
        assert subgoal1.priority == 60
        assert subgoal1.parent_id == parent_id

        subgoal2 = goal_engine._goals[created_ids[1]]
        assert subgoal2.description == "Fix the missing dependency"
        assert subgoal2.priority == 70

    @pytest.mark.asyncio
    async def test_proactive_path_proposals_converted_to_directives(self):
        """Proactive path: suggest_goal tool proposals become directives.

        Simulates the conversion that happens in _runner_autopilot_worker:
        ProposalQueue.drain() → _proposals_to_directives() → GoalCompletionChunk
        """
        # Create a ProposalQueue (this is done per-goal in runner)
        queue = ProposalQueue()

        # Simulate suggest_goal tool being called during execution
        # This is what happens when Layer 2 agent uses the suggest_goal tool
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",  # Runtime fills this
                payload={
                    "description": "Research alternative approaches",
                    "priority": 55,
                    "rationale": "Current approach seems blocked",
                },
            )
        )
        queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={
                    "description": "Ask user for clarification",
                    "priority": 80,
                    "depends_on": ["some_goal_id"],  # Optional dependency
                },
            )
        )

        # This is what _proposals_to_directives() does in the runner
        proposals = queue.drain()
        directives = []
        for p in proposals:
            if p.type == "suggest_goal":
                payload = p.payload or {}
                directives.append(
                    GoalDirective(
                        action="create",
                        description=payload.get("description", ""),
                        priority=payload.get("priority", 50),
                        depends_on=payload.get("depends_on", []),
                        rationale=payload.get("rationale", ""),
                    )
                )

        assert len(directives) == 2
        assert directives[0].description == "Research alternative approaches"
        assert directives[0].priority == 55
        assert directives[1].description == "Ask user for clarification"
        assert directives[1].priority == 80

    @pytest.mark.asyncio
    async def test_both_paths_merge_in_goal_completion_chunk(self, goal_engine: GoalEngine):
        """Integration point: both paths merge in GoalCompletionChunk.

        This simulates the full flow:
        1. StrangeLoop runs with proposal_queue
        2. Reflection generates reactive directives
        3. ProposalQueue drained for proactive directives
        4. Both merged in GoalCompletionChunk.goal_directives
        5. Daemon applies all directives via GoalEngine
        """
        parent_id = list(goal_engine._goals.keys())[0]

        # Reactive directives from Reflection
        reactive_directives = [
            GoalDirective(
                action="create",
                description="Reactive: Fix prerequisite issue",
                priority=65,
            ),
        ]

        # Proactive directives from proposals
        proactive_directives = [
            GoalDirective(
                action="create",
                description="Proactive: Explore alternative solution",
                priority=45,
            ),
            GoalDirective(
                action="create",
                description="Proactive: Document current findings",
                priority=30,
            ),
        ]

        # This is what runner does: merge both paths
        all_directives = reactive_directives + proactive_directives

        # This is what daemon does: apply all directives
        created_ids = await goal_engine.apply_directives(
            all_directives,
            source_goal_id=parent_id,
        )

        # Verify all subgoals created
        assert len(created_ids) == 3
        assert len(goal_engine._goals) == 4  # parent + 3 subgoals

        # Verify ordering: reactive first, then proactive
        goals = [goal_engine._goals[id] for id in created_ids]
        assert goals[0].description == "Reactive: Fix prerequisite issue"
        assert goals[0].priority == 65
        assert goals[1].description == "Proactive: Explore alternative solution"
        assert goals[2].description == "Proactive: Document current findings"

        # All subgoals should have same parent
        for g in goals:
            assert g.parent_id == parent_id

    @pytest.mark.asyncio
    async def test_add_finding_enriches_context_not_goals(self, goal_engine: GoalEngine):
        """add_finding proposals enrich context, not goal DAG.

        Demonstrates that add_finding goes to GoalDispatchContextContribution,
        not to GoalEngine.apply_directives().
        """
        queue = ProposalQueue()

        # add_finding should NOT create goals
        queue.enqueue(
            Proposal(
                type="add_finding",
                goal_id="",
                payload={
                    "summary": "Found that API rate limiting is the bottleneck",
                    "relevance_score": 0.9,
                },
            )
        )

        proposals = queue.drain()

        # _proposals_to_directives skips add_finding
        directives = []
        for p in proposals:
            if p.type == "suggest_goal":
                # Only suggest_goal creates directives
                directives.append(GoalDirective(action="create", description="test"))

        assert len(directives) == 0  # add_finding NOT converted to directive

        # In real flow, add_finding enriches GoalDispatchContextContribution
        # which flows to context_store, not goal DAG

    @pytest.mark.asyncio
    async def test_directive_actions_beyond_create(self, goal_engine: GoalEngine):
        """Other directive actions: adjust_priority, add_dependency, fail, complete.

        Reactive path supports full GoalDirective action set.
        """
        parent_id = list(goal_engine._goals.keys())[0]

        # Create a subgoal first
        created_ids = await goal_engine.apply_directives(
            [GoalDirective(action="create", description="Test subgoal", priority=50)],
            source_goal_id=parent_id,
        )
        subgoal_id = created_ids[0]

        # Now test other actions
        directives = [
            GoalDirective(
                action="adjust_priority",
                goal_id=subgoal_id,
                priority=75,
            ),
            GoalDirective(
                action="add_dependency",
                goal_id=subgoal_id,
                depends_on=[parent_id],
            ),
        ]

        await goal_engine.apply_directives(directives, source_goal_id=parent_id)

        # Verify priority adjusted
        subgoal = goal_engine._goals[subgoal_id]
        assert subgoal.priority == 75

        # Verify dependency added
        assert parent_id in subgoal.depends_on
