"""Per-loop FIFO inbox for clarification requests captured during CoreAgent streams.

Provides `RelayInbox` and `RelayInboxEntry`. Never drops interrupts: every
`ask_user` / `tool_approval` interrupt from every step enters via `enqueue`.
The originating step halts (its CoreAgent thread is checkpointed with the
pending LangGraph interrupt) and resumes via `Command(resume=...)` when its
entry reaches the head and is answered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.sloop.clarification.protocol import ClarificationRequest
    from soothe.sloop.relay.ticket import ResumeTicket

logger = logging.getLogger(__name__)


@dataclass
class RelayInboxEntry:
    """One captured clarification request plus its resume ticket."""

    request: ClarificationRequest
    resume_ticket: ResumeTicket
    step_id: str | None = None


@dataclass
class RelayInbox:
    """Per-loop FIFO queue of captured clarification requests."""

    _entries: list[RelayInboxEntry] = field(default_factory=list)

    def enqueue(
        self,
        request: ClarificationRequest,
        *,
        resume_ticket: ResumeTicket,
        step_id: str | None = None,
    ) -> None:
        """Add a clarification request to the back of the queue."""
        self._entries.append(
            RelayInboxEntry(request=request, resume_ticket=resume_ticket, step_id=step_id)
        )
        logger.info(
            "[RelayInbox] enqueued interrupt_id=%s step_id=%s queue_len=%d",
            request.origin_interrupt_id[:16],
            step_id,
            len(self._entries),
        )

    def peek(self) -> RelayInboxEntry | None:
        """Return the head entry without removing it."""
        return self._entries[0] if self._entries else None

    def dequeue(self) -> RelayInboxEntry | None:
        """Remove and return the head entry (after it has been answered)."""
        if not self._entries:
            return None
        entry = self._entries.pop(0)
        logger.info(
            "[RelayInbox] dequeued interrupt_id=%s queue_len=%d",
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

    def __iter__(self):
        """Iterate entries in FIFO order (for projection / diagnostics)."""
        return iter(list(self._entries))


__all__ = [
    "RelayInbox",
    "RelayInboxEntry",
]
