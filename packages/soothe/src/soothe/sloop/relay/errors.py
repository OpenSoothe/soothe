"""Typed error hierarchy for the LoopRelay bridge.

Every relay operation that can fail raises a `RelayError` subclass so the
StrangeLoop graph can route the failure to the correct station
(`AWAIT_USER` for re-askable mismatches, `DISPATCH` for stale interrupts,
`FINALIZE` for unrecoverable capture failures) instead of crashing the loop.
"""

from __future__ import annotations


class RelayError(Exception):
    """Base for all LoopRelay failures.

    Attributes:
        origin: Clarification origin involved in the failure, if known.
        ticket_id: ResumeTicket thread_id involved, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        origin: str | None = None,
        ticket_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.origin = origin
        self.ticket_id = ticket_id


class RelayStaleInterruptError(RelayError):
    """The head interrupt no longer matches the snapshot captured at park time.

    Routing: `DISPATCH` (skip the resume, treat the interrupt as resolved).
    """


class RelayConcurrentResumeError(RelayError):
    """Another worker already holds the per-thread resume slot.

    Routing: no-op return (the holding worker owns the resume).
    """


class RelayResumeMismatchError(RelayError):
    """The answer shape does not match the origin's expected resume payload.

    Routing: `AWAIT_USER` (re-ask with the mismatch reason surfaced).
    """


class RelayCaptureError(RelayError):
    """A `GraphInterrupt` could not be parsed into a ClarificationRequest.

    Unrecoverable — the CoreAgent thread is left in a checkpointed state the
    loop cannot resume from. Routing: `FINALIZE` with a fatal
    `StepExecutionRecord`.
    """


__all__ = [
    "RelayCaptureError",
    "RelayConcurrentResumeError",
    "RelayError",
    "RelayResumeMismatchError",
    "RelayStaleInterruptError",
]
