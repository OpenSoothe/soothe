"""proposal queue (soothe.cognition.proposal_queue)."""

from datetime import UTC, datetime

from soothe.cognition.goal_engine.proposal_queue import Proposal, ProposalQueue


class TestProposal:
    """Tests for the Proposal dataclass."""

    def test_defaults(self) -> None:
        proposal = Proposal(type="report_progress", goal_id="abc12345", payload={})
        assert proposal.type == "report_progress"
        assert proposal.goal_id == "abc12345"
        assert proposal.payload == {}
        assert proposal.timestamp is not None

    def test_custom_timestamp(self) -> None:
        ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=UTC)
        proposal = Proposal(type="suggest_goal", goal_id="x", payload={"key": "val"}, timestamp=ts)
        assert proposal.timestamp == ts
        assert proposal.payload == {"key": "val"}


class TestProposalQueue:
    """Tests for the ProposalQueue class."""

    def test_initially_empty(self) -> None:
        queue = ProposalQueue()
        assert queue.is_empty() is True

    def test_enqueue_adds_proposal(self) -> None:
        queue = ProposalQueue()
        queue.enqueue(Proposal(type="report_progress", goal_id="g1", payload={}))
        assert queue.is_empty() is False

    def test_drain_returns_all_and_clears(self) -> None:
        queue = ProposalQueue()
        queue.enqueue(Proposal(type="report_progress", goal_id="g1", payload={"status": "50%"}))
        queue.enqueue(Proposal(type="add_finding", goal_id="g1", payload={"content": "Found X"}))
        queue.enqueue(
            Proposal(type="suggest_goal", goal_id="g1", payload={"description": "New goal"})
        )
        queue.enqueue(Proposal(type="flag_blocker", goal_id="g1", payload={"reason": "Blocked"}))

        results = queue.drain()
        assert len(results) == 4
        assert queue.is_empty() is True

    def test_drain_twice_returns_empty(self) -> None:
        queue = ProposalQueue()
        queue.enqueue(Proposal(type="report_progress", goal_id="g1", payload={}))
        first = queue.drain()
        second = queue.drain()
        assert len(first) == 1
        assert len(second) == 0

    def test_preserves_order(self) -> None:
        queue = ProposalQueue()
        types = ["report_progress", "add_finding", "suggest_goal"]
        for t in types:
            queue.enqueue(Proposal(type=t, goal_id="g1", payload={}))  # type: ignore[arg-type]
        results = queue.drain()
        assert [r.type for r in results] == types

    def test_payload_preserved(self) -> None:
        queue = ProposalQueue()
        payload = {"status": "done", "findings": "data processed", "nested": {"key": "val"}}
        queue.enqueue(Proposal(type="report_progress", goal_id="g1", payload=payload))
        result = queue.drain()[0]
        assert result.payload == payload
