"""Tests for _proposals_to_directives helper (RFC-204 Group C)."""

from soothe.autopilot.proposal_queue import Proposal
from soothe.runner._runner_autopilot_worker import _proposals_to_directives


class TestProposalsToDirectives:
    """Test conversion of proposals to GoalDirectives."""

    def test_empty_proposals_returns_empty_list(self) -> None:
        """Empty proposal list returns empty directives."""
        result = _proposals_to_directives([], source_goal_id="g1")
        assert result == []

    def test_suggest_goal_converts_to_create_directive(self) -> None:
        """suggest_goal proposal becomes 'create' directive."""
        proposals = [
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={
                    "description": "Analyze data",
                    "priority": 80,
                    "depends_on": ["dep1"],
                    "rationale": "Need this first",
                },
            ),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert len(directives) == 1
        d = directives[0]
        assert d.action == "create"
        assert d.description == "Analyze data"
        assert d.priority == 80
        assert d.parent_id is None  # Defaults in apply_directives
        assert d.depends_on == ["dep1"]
        assert d.rationale == "Need this first"

    def test_add_finding_not_converted_to_directive(self) -> None:
        """add_finding proposals don't become directives."""
        proposals = [
            Proposal(
                type="add_finding",
                goal_id="",
                payload={
                    "summary": "Found key insight",
                    "relevance_score": 0.9,
                    "tags": ["important"],
                },
            ),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert len(directives) == 0  # Findings don't become directives

    def test_mixed_proposals_only_creates_for_suggest_goal(self) -> None:
        """Only suggest_goal creates directives in mixed queue."""
        proposals = [
            Proposal(type="suggest_goal", goal_id="", payload={"description": "Task A"}),
            Proposal(type="add_finding", goal_id="", payload={"summary": "Insight"}),
            Proposal(type="suggest_goal", goal_id="", payload={"description": "Task B"}),
            Proposal(type="report_progress", goal_id="", payload={"status": "in progress"}),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert len(directives) == 2
        assert directives[0].description == "Task A"
        assert directives[1].description == "Task B"

    def test_suggest_goal_missing_description_skipped(self) -> None:
        """suggest_goal without description is skipped."""
        proposals = [
            Proposal(type="suggest_goal", goal_id="", payload={"description": ""}),
            Proposal(type="suggest_goal", goal_id="", payload={"description": "Valid"}),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert len(directives) == 1
        assert directives[0].description == "Valid"

    def test_suggest_goal_default_priority(self) -> None:
        """Default priority is 50 if not specified."""
        proposals = [
            Proposal(type="suggest_goal", goal_id="", payload={"description": "test"}),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert directives[0].priority == 50

    def test_multiple_suggest_goals_preserve_order(self) -> None:
        """Order is preserved when multiple suggest_goal proposals."""
        proposals = [
            Proposal(type="suggest_goal", goal_id="", payload={"description": "first"}),
            Proposal(type="suggest_goal", goal_id="", payload={"description": "second"}),
            Proposal(type="suggest_goal", goal_id="", payload={"description": "third"}),
        ]

        directives = _proposals_to_directives(proposals, source_goal_id="g_parent")

        assert len(directives) == 3
        assert [d.description for d in directives] == ["first", "second", "third"]
