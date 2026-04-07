"""Tests for RFC-204 Layer 2 proposal queuing integration.

Covers: End-to-end proposal flow from enqueue to drain.
"""

import pytest

from soothe.cognition.proposal_queue import Proposal, ProposalQueue


class TestProposalFlow:
    """Verify proposal flow from tool to processor."""

    @pytest.mark.asyncio
    async def test_report_progress_flow(self) -> None:
        """ReportProgress tool -> enqueue -> drain -> apply."""
        q = ProposalQueue()
        # Simulate tool enqueueing
        q.enqueue(
            Proposal(
                type="report_progress",
                goal_id="g1",
                payload={"status": "in progress", "findings": "found 3 items"},
            )
        )
        # Simulate _process_proposals draining
        proposals = q.drain()
        assert len(proposals) == 1
        p = proposals[0]
        assert p.type == "report_progress"
        assert p.payload["status"] == "in progress"
        assert p.payload["findings"] == "found 3 items"

    @pytest.mark.asyncio
    async def test_suggest_goal_flow(self) -> None:
        q = ProposalQueue()
        q.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={"description": "Analyze dataset", "priority": 80},
            )
        )
        proposals = q.drain()
        assert len(proposals) == 1
        assert proposals[0].payload["description"] == "Analyze dataset"
        assert proposals[0].payload["priority"] == 80

    @pytest.mark.asyncio
    async def test_flag_blocker_flow(self) -> None:
        q = ProposalQueue()
        q.enqueue(
            Proposal(
                type="flag_blocker",
                goal_id="g1",
                payload={"reason": "External API unavailable"},
            )
        )
        proposals = q.drain()
        assert len(proposals) == 1
        assert proposals[0].payload["reason"] == "External API unavailable"

    @pytest.mark.asyncio
    async def test_mixed_proposals(self) -> None:
        q = ProposalQueue()
        for ptype in ["report_progress", "suggest_goal", "add_finding", "flag_blocker"]:
            q.enqueue(Proposal(type=ptype, goal_id="g1", payload={"test": True}))
        proposals = q.drain()
        types = [p.type for p in proposals]
        assert types == ["report_progress", "suggest_goal", "add_finding", "flag_blocker"]

    @pytest.mark.asyncio
    async def test_queue_clears_on_drain(self) -> None:
        q = ProposalQueue()
        q.enqueue(Proposal(type="report_progress", goal_id="g1", payload={}))
        q.drain()
        assert q.is_empty()
