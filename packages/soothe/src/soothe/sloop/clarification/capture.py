"""Side-channel for capturing clarification requests during a CoreAgent stream."""

from __future__ import annotations

from dataclasses import dataclass

from soothe.sloop.clarification.protocol import ClarificationRequest


@dataclass
class ClarificationCapture:
    """First-wins capture of a clarification request emitted mid-stream.

    The CoreAgent stream wrapper writes here when it detects an ``ask_user``
    interrupt or a heuristic plain-text question. The originating loop node
    reads the captured request after the stream ends and threads it into
    ``pending_clarification`` so the graph router dispatches to
    ``await_clarification``.
    """

    pending_request: ClarificationRequest | None = None

    def set(self, request: ClarificationRequest) -> None:
        if self.pending_request is None:
            self.pending_request = request


__all__ = ["ClarificationCapture"]
