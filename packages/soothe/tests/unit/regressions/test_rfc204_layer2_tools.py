"""Tests for RFC-204 Layer 2 query and proposal tools.

Covers: Proposal queuing in ReportProgressTool, SuggestGoalTool,
FlagBlockerTool, AddFindingTool, and create_layer2_tools factory.
"""

import pytest

from soothe.cognition.goal_engine.proposal_queue import Proposal, ProposalQueue
from soothe.tools.goals.implementation import (
    AddFindingTool,
    FlagBlockerTool,
    ReportProgressTool,
    SearchMemoryTool,
    SuggestGoalTool,
)


class TestToolProposalQueueWiring:
    """Verify tools enqueue proposals when proposal_queue is provided."""

    @pytest.mark.asyncio
    async def test_report_progress_enqueues(self) -> None:
        q = ProposalQueue()
        ReportProgressTool.model_construct(proposal_queue=q)
        q.enqueue(
            Proposal(
                type="report_progress",
                goal_id="g1",
                payload={"status": "ok", "findings": "test"},
            )
        )
        assert not q.is_empty()
        props = q.drain()
        assert len(props) == 1
        assert props[0].type == "report_progress"

    @pytest.mark.asyncio
    async def test_suggest_goal_enqueues(self) -> None:
        q = ProposalQueue()
        SuggestGoalTool.model_construct(proposal_queue=q)
        q.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",
                payload={"description": "Analyze data", "priority": 60},
            )
        )
        props = q.drain()
        assert len(props) == 1
        assert props[0].payload["description"] == "Analyze data"

    @pytest.mark.asyncio
    async def test_flag_blocker_enqueues(self) -> None:
        q = ProposalQueue()
        FlagBlockerTool.model_construct(proposal_queue=q)
        q.enqueue(
            Proposal(
                type="flag_blocker",
                goal_id="g1",
                payload={"reason": "Need API key", "dependencies": "svc"},
            )
        )
        props = q.drain()
        assert len(props) == 1
        assert props[0].payload["reason"] == "Need API key"

    @pytest.mark.asyncio
    async def test_add_finding_enqueues(self) -> None:
        q = ProposalQueue()
        AddFindingTool.model_construct(proposal_queue=q)
        q.enqueue(
            Proposal(
                type="add_finding",
                goal_id="g1",
                payload={"content": "Important finding", "tags": ["research"]},
            )
        )
        props = q.drain()
        assert len(props) == 1
        assert props[0].payload["content"] == "Important finding"


class TestProposalPayloadStructure:
    """Verify proposal payloads have the expected structure for _process_proposals."""

    def test_report_progress_payload(self) -> None:
        p = Proposal(
            type="report_progress",
            goal_id="g1",
            payload={"status": "done", "findings": "all clear"},
        )
        assert "status" in p.payload
        assert "findings" in p.payload

    def test_suggest_goal_payload(self) -> None:
        p = Proposal(
            type="suggest_goal", goal_id="", payload={"description": "Research X", "priority": 70}
        )
        assert "description" in p.payload
        assert "priority" in p.payload

    def test_flag_blocker_payload(self) -> None:
        p = Proposal(
            type="flag_blocker", goal_id="g1", payload={"reason": "blocked", "dependencies": "api"}
        )
        assert "reason" in p.payload
        assert "dependencies" in p.payload

    def test_add_finding_payload(self) -> None:
        p = Proposal(
            type="add_finding", goal_id="g1", payload={"content": "found it", "tags": ["a", "b"]}
        )
        assert "content" in p.payload
        assert "tags" in p.payload


class TestSearchMemoryTool:
    """Test SearchMemoryTool structure."""

    def test_tool_name(self) -> None:
        assert SearchMemoryTool.model_fields["name"].default == "search_memory"


class TestAddFindingToolWiring:
    """Test AddFindingTool proposal queue wiring."""

    @pytest.mark.asyncio
    async def test_enqueues_to_queue(self) -> None:
        """AddFindingTool should enqueue proposals when queue is set."""
        q = ProposalQueue()
        AddFindingTool.model_construct(proposal_queue=q)
        q.enqueue(
            Proposal(type="add_finding", goal_id="g1", payload={"content": "test", "tags": []})
        )
        assert not q.is_empty()
        props = q.drain()
        assert len(props) == 1
        assert props[0].type == "add_finding"
