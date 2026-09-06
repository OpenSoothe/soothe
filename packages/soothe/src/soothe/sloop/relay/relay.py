"""LoopRelay — the single typed bridge between StrangeLoop and CoreAgent graphs.

Owns the interrupt → park → resume lifecycle for one StrangeLoop run: capture
from a `GraphInterrupt`, origin-aware routing, `Command(resume=...)` building
(live `interrupt()` or orphan goto), per-thread resume locking, stale-head
detection, and projection of inbox + scratch to the `relay_state` channel so
state survives worker restarts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.sloop.relay.channel import (
    build_relay_state_update,
    hydrate_inbox,
    hydrate_scratch_from_relay_state,
)
from soothe.sloop.relay.errors import (
    RelayCaptureError,
    RelayConcurrentResumeError,
    RelayResumeMismatchError,
    RelayStaleInterruptError,
)
from soothe.sloop.relay.events import (
    RELAY_CAPTURED,
    RELAY_DEFERRED,
    RELAY_RECOVERED,
    RELAY_RESUME_COMMAND_BUILT,
    RELAY_STALE_INTERRUPT_SKIPPED,
    RELAY_UNBLOCKED,
)
from soothe.sloop.relay.inbox import RelayInbox
from soothe.sloop.relay.outbox import build_clarification_resume_payload
from soothe.sloop.relay.router import (
    PauseMode,
    pause_mode_for_origin,
    resume_node_for_clarification_origin,
)
from soothe.sloop.relay.snapshot import (
    snapshot_has_resumable_interrupt,
    snapshot_has_unanswered_pending,
)
from soothe.sloop.relay.ticket import ResumeTicket

if TYPE_CHECKING:
    from langgraph.errors import GraphInterrupt

    from soothe.sloop.clarification.detector import ClarificationDetector
    from soothe.sloop.clarification.protocol import (
        ClarificationAnswer,
        ClarificationRequest,
        LoopStateView,
    )
    from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch

logger = logging.getLogger(__name__)


@dataclass
class CaptureOutcome:
    """Result of `LoopRelay.capture_interrupt`.

    Attributes:
        halt_step: When True, the originating step halts and the graph routes
            to `AWAIT_USER`.
        channel_update: `{"relay_state": {...}}` for the node to return so the
            inbox + scratch survive the park.
        error: Non-None when capture failed; the caller routes to `FINALIZE`.
    """

    halt_step: bool
    channel_update: dict[str, Any] = field(default_factory=dict)
    error: RelayCaptureError | None = None


@dataclass
class RouteDecision:
    """Where the loop graph goes after a capture or on resume.

    Attributes:
        resume_node: Station name (`EXECUTE` / `PLAN_REVIEW`), or `None` for
            host-only origins.
        pause_mode: `interactive` (LangGraph `interrupt()`) or `hard_defer`
            (CE park + out-of-band resume).
    """

    resume_node: str | None
    pause_mode: PauseMode


@dataclass
class RelaySnapshot:
    """Serializable view of relay state for diagnostics and stale-check."""

    inbox_len: int
    active_origin: str | None
    head_ticket_id: str | None
    audit_len: int


def _extract_interrupts_from_graph_interrupt(exc: GraphInterrupt) -> dict[str, Any]:
    """Extract the `{interrupt_id: payload}` mapping from a `GraphInterrupt`.

    LangGraph stores pending interrupts on `exc.args[0]` as a list of objects
    with `.id` and `.value`. Returns `{}` when the exception shape is
    unexpected (defensive).
    """
    args = getattr(exc, "args", None) or ()
    if not args:
        return {}
    raw = args[0]
    if isinstance(raw, Mapping):
        return dict(raw)
    result: dict[str, Any] = {}
    if isinstance(raw, (list, tuple)):
        for item in raw:
            iid = getattr(item, "id", None) or ""
            value = getattr(item, "value", None)
            if iid and value is not None:
                result[str(iid)] = value
    return result


class LoopRelay:
    """Single typed bridge between the StrangeLoop and CoreAgent graphs.

    Owns the full interrupt → park → resume lifecycle for one StrangeLoop run.
    Reentrant across worker exits: all state is projected to the `relay_state`
    channel before parking and rehydrated on resume.

    Example:
        relay = LoopRelay(loop_id="loop-1", emit=emit)
        outcome = await relay.capture_interrupt(exc=gi, origin="execute", ...)
        if outcome.halt_step:
            node_returns = outcome.channel_update  # route to AWAIT_USER
    """

    def __init__(
        self,
        *,
        loop_id: str,
        emit: Callable[[str, Any], Awaitable[None]],
        inbox: RelayInbox | None = None,
    ) -> None:
        self._loop_id = loop_id
        self._emit = emit
        self._inbox: RelayInbox = inbox if inbox is not None else RelayInbox()
        self._active_origin: str | None = None
        self._audit: list[dict[str, Any]] = []
        self._locks: dict[str, asyncio.Lock] = {}
        self._parked_head_ticket_id: str | None = None

    @property
    def inbox(self) -> RelayInbox:
        """The in-memory inbox (mirrored to the `relay_state` channel)."""
        return self._inbox

    @property
    def active_origin(self) -> str | None:
        """Origin of the current head, or `None` when the inbox is empty."""
        if self._inbox.head is not None:
            return self._inbox.head.origin_node
        return self._active_origin

    # ------------------------------------------------------------------
    # Capture (CoreAgent → StrangeLoop)
    # ------------------------------------------------------------------

    async def capture_interrupt(
        self,
        *,
        exc: GraphInterrupt,
        origin: str,
        ticket: ResumeTicket,
        step_id: str | None,
        detector: ClarificationDetector,
        loop_state_view: LoopStateView,
        scratch: LoopPhaseScratch | None = None,
    ) -> CaptureOutcome:
        """Catch a `GraphInterrupt` from a CoreAgent stream and enqueue it.

        Parses the interrupt, classifies via the detector, enqueues the
        resulting `ClarificationRequest`, projects inbox + scratch to the
        `relay_state` channel, emits `RELAY_CAPTURED`, and returns a
        `CaptureOutcome` telling the caller to halt and route to `AWAIT_USER`.
        On a malformed interrupt, returns `error` so the caller routes to
        `FINALIZE`.
        """
        try:
            interrupts = _extract_interrupts_from_graph_interrupt(exc)
        except Exception as exc_parse:  # noqa: BLE001
            err = RelayCaptureError(
                f"failed to parse GraphInterrupt: {exc_parse}",
                origin=origin,
                ticket_id=ticket.thread_id,
            )
            self._audit.append(self._audit_entry("capture_failed", origin, ticket))
            return CaptureOutcome(halt_step=False, error=err)

        captured = None
        for interrupt_id, value in interrupts.items():
            request = detector.detect(
                value,
                interrupt_id=interrupt_id,
                loop_state=loop_state_view,
                origin_node=origin,  # type: ignore[arg-type]
            )
            if request is not None:
                captured = request
                break

        if captured is None:
            self._audit.append(self._audit_entry("capture_empty", origin, ticket))
            return CaptureOutcome(halt_step=False)

        self._inbox.enqueue(
            captured,
            resume_ticket=ticket,
            step_id=step_id,
        )
        self._active_origin = captured.origin_node
        self._audit.append(self._audit_entry("captured", captured.origin_node, ticket))

        channel_update = build_relay_state_update(
            inbox=self._inbox,
            scratch=scratch,
            active_origin=self._active_origin,
            answer=None,
            audit=self._audit,
        )
        await self._emit(
            RELAY_CAPTURED,
            {
                "loop_id": self._loop_id,
                "origin": captured.origin_node,
                "interrupt_id": captured.origin_interrupt_id[:16],
                "step_id": step_id,
                "thread_id": ticket.thread_id,
                "queue_len": len(self._inbox),
            },
        )
        return CaptureOutcome(halt_step=True, channel_update=channel_update)

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------

    def route_captured(self) -> RouteDecision:
        """Decide where the loop graph goes after a capture.

        Reads the head's origin and returns the resume station + pause mode.
        Returns a no-op decision (`resume_node=None`) when the inbox is empty.
        """
        head = self._inbox.head
        if head is None:
            return RouteDecision(resume_node=None, pause_mode="hard_defer")
        return RouteDecision(
            resume_node=resume_node_for_clarification_origin(head.origin_node),
            pause_mode=pause_mode_for_origin(head.origin_node),
        )

    # ------------------------------------------------------------------
    # Resume (StrangeLoop → CoreAgent)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def resume_slot(self, ticket_id: str):
        """Acquire the per-thread resume slot for a fork thread.

        Serializes resume per `ticket.thread_id` so two parallel step threads
        cannot race the same CoreAgent fork; parallel across threads. Raises
        `RelayConcurrentResumeError` only on reentrancy within the same task.
        """
        lock = self._locks.get(ticket_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[ticket_id] = lock
        if lock.locked() and asyncio.current_task() in getattr(lock, "_waiters_cancelled", set()):
            raise RelayConcurrentResumeError(
                "reentrant resume on the same task",
                ticket_id=ticket_id,
            )
        async with lock:
            yield

    async def build_resume_command(
        self,
        *,
        answers: list[str],
        snapshot: Any,
        relay_state: Mapping[str, Any] | None,
    ) -> Any | None:
        """Build the StrangeLoop-level `Command` to resume a parked clarification.

        - Live `interrupt()`: returns `Command(resume={"answers": [...]})`.
        - Orphaned (no live interrupt after a worker crash): looks up the
          origin from `relay_state` and returns
          `Command(update={...answer...}, goto=resume_node)`.
        - No pending: returns `None` (defensive against a stale resume flag).

        Raises `RelayStaleInterruptError` if the live head drifted from the
        ticket persisted at park time; the caller catches it, emits
        `RELAY_STALE_INTERRUPT_SKIPPED`, and routes to `DISPATCH`.
        """
        from soothe.sloop.clarification.protocol import (
            ClarificationAnswer,
            answer_to_state,
        )
        from soothe.sloop.relay._adapter import (
            build_live_interrupt_resume_command,
            build_orphan_goto_command,
        )

        if not snapshot_has_unanswered_pending(snapshot):
            logger.info("[relay] no unanswered pending in snapshot; no resume command")
            return None

        self._check_stale_head(relay_state)

        if snapshot_has_resumable_interrupt(snapshot):
            cmd = build_live_interrupt_resume_command(answers)
            await self._emit(
                RELAY_RESUME_COMMAND_BUILT,
                {"loop_id": self._loop_id, "shape": "live_interrupt", "answers": len(answers)},
            )
            return cmd

        origin = self._origin_from_relay_state(relay_state)
        goto = resume_node_for_clarification_origin(origin)
        if goto is None:
            logger.error(
                "[relay] orphaned pending without a safe resume station (loop=%s origin=%s)",
                self._loop_id,
                origin,
            )
            return None
        answer_state = answer_to_state(ClarificationAnswer(answers=tuple(answers), source="human"))
        cmd = build_orphan_goto_command(
            answer_state=answer_state,
            goto=goto,
            relay_state=relay_state,
        )
        await self._emit(
            RELAY_RESUME_COMMAND_BUILT,
            {
                "loop_id": self._loop_id,
                "shape": "orphan_goto",
                "origin": origin,
                "goto": goto,
            },
        )
        return cmd

    def build_core_agent_resume_payload(
        self,
        *,
        request: ClarificationRequest,
        answer: ClarificationAnswer,
    ) -> dict[str, Any]:
        """Build the CoreAgent-level `Command(resume=...)` payload.

        Delegates to `outbox.build_clarification_resume_payload`. Raises
        `RelayResumeMismatchError` when the answer is empty for a non-
        tool-approval origin.
        """
        if not answer.answers and request.origin_node != "tool_approval":
            raise RelayResumeMismatchError(
                "empty answer for non-tool-approval origin",
                origin=request.origin_node,
            )
        return build_clarification_resume_payload(request, answer)

    def _check_stale_head(self, relay_state: Mapping[str, Any] | None) -> None:
        """Raise `RelayStaleInterruptError` if the live head drifted from park time."""
        if not isinstance(relay_state, Mapping):
            return
        parked_id = relay_state.get("parked_head_ticket_id")
        live_head = self._inbox.peek()
        live_id = live_head.resume_ticket.thread_id if live_head else None
        if parked_id and live_id and parked_id != live_id:
            raise RelayStaleInterruptError(
                f"head drifted: parked={parked_id[:16]} live={live_id[:16]}",
                ticket_id=live_id,
            )

    def _origin_from_relay_state(self, relay_state: Mapping[str, Any] | None) -> str | None:
        """Read the active origin from `relay_state` (or its inbox head)."""
        if not isinstance(relay_state, Mapping):
            return None
        origin = relay_state.get("active_origin")
        if origin:
            return str(origin)
        inbox = relay_state.get("inbox")
        if isinstance(inbox, list) and inbox:
            head = inbox[0]
            if isinstance(head, Mapping):
                request = head.get("request")
                if isinstance(request, Mapping):
                    return request.get("origin_node")
        return None

    # ------------------------------------------------------------------
    # Answer lifecycle (await_user + origin node)
    # ------------------------------------------------------------------

    def record_answer(
        self,
        *,
        answer: ClarificationAnswer,
        scratch: LoopPhaseScratch | None = None,
    ) -> dict[str, Any]:
        """Record a policy answer onto the relay state (called by `await_user`).

        Returns `{"relay_state": {..., "answer": answer_state}}` for the node
        to return. The origin node consumes the answer via `consume_answer`
        and dequeues the head after the CoreAgent resume succeeds.
        """
        from soothe.sloop.clarification.protocol import answer_to_state

        answer_state = answer_to_state(answer)
        self._audit.append(
            self._audit_entry(
                "answered",
                self.active_origin,
                self._inbox.head_ticket,
            )
        )
        return build_relay_state_update(
            inbox=self._inbox,
            scratch=scratch,
            active_origin=self.active_origin,
            answer=answer_state,
            audit=self._audit,
        )

    def consume_answer(
        self,
        relay_state: Mapping[str, Any] | None,
    ) -> tuple[ClarificationRequest, ClarificationAnswer, ResumeTicket] | None:
        """Pop the head + answer for the origin node to build a CoreAgent resume.

        Called by the origin node (`execute` / `plan_review`) after the policy
        answered. Returns `(request, answer, ticket)` or `None` when the
        inbox/answer is empty. Dequeues the head; the next `project_to_channels`
        call reflects the dequeue.
        """
        from soothe.sloop.clarification.protocol import answer_from_state

        if not isinstance(relay_state, Mapping):
            return None
        answer_state = relay_state.get("answer")
        if not isinstance(answer_state, Mapping):
            return None
        head_entry = self._inbox.peek()
        if head_entry is None:
            return None
        try:
            answer = answer_from_state(answer_state)
        except ValueError:
            logger.exception("[relay] malformed answer state on consume")
            return None
        request = head_entry.request
        ticket = head_entry.resume_ticket
        self._inbox.dequeue()
        self._audit.append(self._audit_entry("consumed", request.origin_node, ticket))
        return request, answer, ticket

    def clear_answer(self, *, scratch: LoopPhaseScratch | None = None) -> dict[str, Any]:
        """Clear the answer slot and project the dequeued inbox (origin node, post-resume)."""
        return build_relay_state_update(
            inbox=self._inbox,
            scratch=scratch,
            active_origin=self.active_origin,
            answer=None,
            audit=self._audit,
        )

    # ------------------------------------------------------------------
    # Reentrancy — project to channels before park, hydrate on resume
    # ------------------------------------------------------------------

    def project_to_channels(
        self,
        *,
        scratch: LoopPhaseScratch | None = None,
        mark_parked_head: bool = False,
    ) -> dict[str, Any]:
        """Project inbox + scratch into the `relay_state` channel before parking.

        When `mark_parked_head` is True (before a hard-defer / interactive
        pause), stashes the head ticket id so a stale resume is detectable
        after a worker crash + re-dispatch.
        """
        update = build_relay_state_update(
            inbox=self._inbox,
            scratch=scratch,
            active_origin=self.active_origin,
            answer=None,
            audit=self._audit,
        )
        if mark_parked_head:
            head = self._inbox.peek()
            self._parked_head_ticket_id = head.resume_ticket.thread_id if head else None
            update["relay_state"]["parked_head_ticket_id"] = self._parked_head_ticket_id
        return update

    def hydrate_from_channels(
        self,
        relay_state: Mapping[str, Any] | None,
        scratch: LoopPhaseScratch | None = None,
    ) -> None:
        """Rebuild the inbox + scratch from the `relay_state` channel on a fresh worker.

        Called at turn start (`node_execute` / `node_await_clarification`) so a
        fresh `ainvoke` reconstructs inbox and scratch from the checkpoint.
        Idempotent — skips entries already present.
        """
        self._inbox = hydrate_inbox(relay_state)
        if isinstance(relay_state, Mapping):
            parked = relay_state.get("parked_head_ticket_id")
            if parked:
                self._parked_head_ticket_id = str(parked)
            self._audit = list(relay_state.get("audit") or [])
            self._active_origin = self._origin_from_relay_state(relay_state)
        if scratch is not None:
            hydrate_scratch_from_relay_state(scratch, relay_state)

    def snapshot(self, relay_state: Mapping[str, Any] | None = None) -> RelaySnapshot:
        """Return a serializable view for diagnostics and stale-check."""
        head = self._inbox.peek()
        return RelaySnapshot(
            inbox_len=len(self._inbox),
            active_origin=self.active_origin,
            head_ticket_id=head.resume_ticket.thread_id if head else None,
            audit_len=len(self._audit),
        )

    # ------------------------------------------------------------------
    # Event helpers for await_user integration
    # ------------------------------------------------------------------

    async def emit_deferred(self, *, reason: str, questions: tuple) -> None:
        await self._emit(
            RELAY_DEFERRED,
            {"loop_id": self._loop_id, "reason": reason, "questions": list(questions)},
        )

    async def emit_unblocked(self, *, goal_id: str) -> None:
        await self._emit(
            RELAY_UNBLOCKED,
            {"loop_id": self._loop_id, "goal_id": goal_id, "new_status": "pending"},
        )

    async def emit_recovered(self, *, reason: str, origin: str | None = None) -> None:
        await self._emit(
            RELAY_RECOVERED,
            {"loop_id": self._loop_id, "reason": reason, "origin": origin},
        )

    async def emit_stale_skipped(self, *, ticket_id: str) -> None:
        await self._emit(
            RELAY_STALE_INTERRUPT_SKIPPED,
            {"loop_id": self._loop_id, "ticket_id": ticket_id},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _audit_entry(
        self,
        event: str,
        origin: str | None,
        ticket: ResumeTicket | None,
    ) -> dict[str, Any]:
        return {
            "ts": time.time(),
            "event": event,
            "origin": origin,
            "ticket_id": ticket.thread_id if ticket else None,
            "loop_id": self._loop_id,
        }


__all__ = [
    "CaptureOutcome",
    "LoopRelay",
    "RelaySnapshot",
    "RouteDecision",
]
