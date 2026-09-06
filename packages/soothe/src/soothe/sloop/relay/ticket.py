"""Interrupt-resume identity and serialization for graph-channel storage.

Single owner of `ResumeTicket`. The ticket bridges a StrangeLoop interrupt
capture and the CoreAgent fork thread resumed via `Command(resume=...)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass
class ResumeTicket:
    """Interrupt-resume identity for the `relay_state` graph channel.

    Attributes:
        thread_id: CoreAgent fork thread hosting the pending interrupt.
        step_id: Originating step id (for `step_started` re-emit on resume).
        step_description: Originating step description (for TUI card title).
        prior_duration_ms: Pre-interrupt elapsed ms accumulated into the
            final `duration_ms` on resume.
    """

    thread_id: str | None = None
    step_id: str | None = None
    step_description: str | None = None
    prior_duration_ms: int = 0


def ticket_to_state(ticket: ResumeTicket | None) -> dict[str, Any]:
    """Serialize a `ResumeTicket` for graph-channel storage (JSON-safe).

    Returns an empty dict for `None` so callers can merge without None-checks.
    """
    if ticket is None:
        return {}
    return {
        "thread_id": ticket.thread_id,
        "step_id": ticket.step_id,
        "step_description": ticket.step_description,
        "prior_duration_ms": int(ticket.prior_duration_ms or 0),
    }


def ticket_from_state(d: Mapping[str, Any] | None) -> ResumeTicket | None:
    """Inverse of `ticket_to_state`.

    Returns `None` when `d` carries no `thread_id` — a ticket without a thread
    cannot resume (no CoreAgent fork to re-enter).
    """
    if not isinstance(d, Mapping) or not d:
        return None
    thread_id = d.get("thread_id")
    if not thread_id:
        return None
    return ResumeTicket(
        thread_id=str(thread_id),
        step_id=d.get("step_id"),
        step_description=d.get("step_description"),
        prior_duration_ms=int(d.get("prior_duration_ms") or 0),
    )


__all__ = [
    "ResumeTicket",
    "ticket_from_state",
    "ticket_to_state",
]
