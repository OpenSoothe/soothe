"""Per-loop FIFO queue for clarification requests captured during CoreAgent streams."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
            the final `duration_ms` on resume.
    """

    thread_id: str | None = None
    step_id: str | None = None
    step_description: str | None = None
    prior_duration_ms: int = 0


@dataclass
class QueuedClarification:
    """One captured clarification request plus its resume ticket."""

    request: ClarificationRequest
    resume_ticket: ResumeTicket
    step_id: str | None = None


@dataclass
class ClarificationQueue:
    """Per-loop FIFO queue of captured clarification requests.

    Never drops interrupts. Every `ask_user` / `tool_approval` interrupt
    from every step enters via :meth:`enqueue`. The originating step halts
    (its CoreAgent thread is checkpointed with the pending LangGraph interrupt)
    and resumes via `Command(resume=...)` when its entry reaches the head
    and is answered.
    """

    _entries: list[QueuedClarification] = field(default_factory=list)

    def enqueue(
        self,
        request: ClarificationRequest,
        *,
        resume_ticket: ResumeTicket,
        step_id: str | None = None,
    ) -> None:
        """Add a clarification request to the back of the queue."""
        self._entries.append(
            QueuedClarification(request=request, resume_ticket=resume_ticket, step_id=step_id)
        )
        logger.info(
            "[ClarificationQueue] enqueued interrupt_id=%s step_id=%s queue_len=%d",
            request.origin_interrupt_id[:16],
            step_id,
            len(self._entries),
        )

    def peek(self) -> QueuedClarification | None:
        """Return the head entry without removing it."""
        return self._entries[0] if self._entries else None

    def dequeue(self) -> QueuedClarification | None:
        """Remove and return the head entry (after it has been answered)."""
        if not self._entries:
            return None
        entry = self._entries.pop(0)
        logger.info(
            "[ClarificationQueue] dequeued interrupt_id=%s queue_len=%d",
            entry.request.origin_interrupt_id[:16],
            len(self._entries),
        )
        return entry

    @property
    def head(self) -> ClarificationRequest | None:
        """The head clarification request, or `None` if empty."""
        return self.peek().request if self._entries else None

    @property
    def head_ticket(self) -> ResumeTicket | None:
        """Resume ticket for the head entry, or `None` if empty."""
        return self.peek().resume_ticket if self._entries else None

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)


__all__ = ["ClarificationQueue", "QueuedClarification", "ResumeTicket"]
