"""Side-channel for capturing clarification requests during a CoreAgent stream."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.sloop.clarification.protocol import ClarificationRequest

logger = logging.getLogger(__name__)


@dataclass
class ResumeTicket:
    """Interrupt-resume identity carried on one graph channel.

    Attributes:
        thread_id: CoreAgent fork thread hosting the pending interrupt.
        step_id: Originating step id (for step_started re-emit on resume).
        step_description: Originating step description (for TUI card title).
        prior_duration_ms: Pre-interrupt elapsed time (ms) accumulated into
            the final ``duration_ms`` on resume.
    """

    thread_id: str | None = None
    step_id: str | None = None
    step_description: str | None = None
    prior_duration_ms: int = 0


@dataclass
class ClarificationCapture:
    """First-wins capture of a clarification request emitted mid-stream.

    The CoreAgent stream wrapper writes here when it detects a structured
    `ask_user` interrupt. The originating loop node reads the captured
    request after the stream ends and threads it into
    `pending_clarification` so the graph router dispatches to
    `await_clarification`.

    Attributes:
        pending_request: The first captured clarification request (None until set).
        resume_ticket: The interrupt-resume identity (thread + step) captured
            by the executor when a `GraphInterrupt` fires, so the resume path
            can re-enter the CoreAgent on the same thread and re-emit
            `step_started` with the same step the TUI already has a card for.
            See :class:`ResumeTicket`.
    """

    pending_request: ClarificationRequest | None = None
    resume_ticket: ResumeTicket | None = None

    def set(self, request: ClarificationRequest) -> None:
        if self.pending_request is None:
            self.pending_request = request
            return
        logger.warning(
            "[ClarificationCapture] dropping secondary ask_user (first-wins); "
            "kept interrupt_id=%s dropped=%s",
            self.pending_request.origin_interrupt_id,
            request.origin_interrupt_id,
        )


__all__ = ["ClarificationCapture", "ResumeTicket"]
