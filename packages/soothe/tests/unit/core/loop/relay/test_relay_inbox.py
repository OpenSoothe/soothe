"""Tests for the per-loop RelayInbox (FIFO, never drops)."""

from __future__ import annotations

from soothe.sloop.clarification.origins import ORIGIN_EXECUTE, ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import ClarificationRequest, LoopStateView
from soothe.sloop.relay.inbox import RelayInbox, RelayInboxEntry
from soothe.sloop.relay.ticket import ResumeTicket


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="",
        user_request="",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _request(iid: str, origin: str = ORIGIN_TOOL_APPROVAL) -> ClarificationRequest:
    return ClarificationRequest(
        questions=(f"Approve {iid}?",),
        origin_node=origin,  # type: ignore[arg-type]
        origin_interrupt_id=iid,
        loop_state=_view(),
    )


class TestRelayInboxFIFO:
    """The queue preserves every entry in FIFO order — no drops."""

    def test_empty_queue_head_is_none(self) -> None:
        q = RelayInbox()
        assert q.head is None
        assert q.peek() is None
        assert q.head_ticket is None
        assert len(q) == 0
        assert not q

    def test_enqueue_two_preserves_order(self) -> None:
        q = RelayInbox()
        r1 = _request("iii-1")
        r2 = _request("iii-2")
        q.enqueue(r1, resume_ticket=ResumeTicket(thread_id="t1"), step_id="s1")
        q.enqueue(r2, resume_ticket=ResumeTicket(thread_id="t2"), step_id="s2")
        assert len(q) == 2
        assert q.head is r1
        assert q.peek().step_id == "s1"
        assert q.head_ticket.thread_id == "t1"

    def test_dequeue_pops_head_only(self) -> None:
        q = RelayInbox()
        r1 = _request("iii-1")
        r2 = _request("iii-2")
        q.enqueue(r1, resume_ticket=ResumeTicket(), step_id="s1")
        q.enqueue(r2, resume_ticket=ResumeTicket(), step_id="s2")
        popped = q.dequeue()
        assert popped is not None
        assert popped.request is r1
        assert len(q) == 1
        assert q.head is r2

    def test_dequeue_empty_returns_none(self) -> None:
        q = RelayInbox()
        assert q.dequeue() is None

    def test_never_drops_secondary_interrupts(self) -> None:
        """The core defect fix: secondary interrupts are NOT dropped."""
        q = RelayInbox()
        for i in range(5):
            q.enqueue(_request(f"iii-{i}"), resume_ticket=ResumeTicket())
        assert len(q) == 5
        # All five survive — head is the first enqueued.
        assert q.head.origin_interrupt_id == "iii-0"
        # Drain in order
        for i in range(5):
            popped = q.dequeue()
            assert popped is not None
            assert popped.request.origin_interrupt_id == f"iii-{i}"

    def test_resume_ticket_per_entry(self) -> None:
        """Each entry carries its own resume ticket (thread_id)."""
        q = RelayInbox()
        q.enqueue(
            _request("iii-A"),
            resume_ticket=ResumeTicket(thread_id="thread-A", step_id="step-A"),
            step_id="step-A",
        )
        q.enqueue(
            _request("iii-B"),
            resume_ticket=ResumeTicket(thread_id="thread-B", step_id="step-B"),
            step_id="step-B",
        )
        assert q.peek().resume_ticket.thread_id == "thread-A"
        q.dequeue()
        assert q.peek().resume_ticket.thread_id == "thread-B"

    def test_head_and_head_ticket_read_only(self) -> None:
        """head / head_ticket are read-only properties — no setter."""
        q = RelayInbox()
        try:
            q.head = _request("x")  # type: ignore[misc]
            raise AssertionError("should not be settable")
        except AttributeError:
            pass


class TestRelayInboxEntry:
    def test_entry_carries_request_ticket_step(self) -> None:
        req = _request("iii-1", origin=ORIGIN_EXECUTE)
        ticket = ResumeTicket(thread_id="t", step_id="s")
        entry = RelayInboxEntry(request=req, resume_ticket=ticket, step_id="s")
        assert entry.request is req
        assert entry.resume_ticket is ticket
        assert entry.step_id == "s"
