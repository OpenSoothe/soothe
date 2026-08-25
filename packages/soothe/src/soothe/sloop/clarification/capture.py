"""Side-channel for capturing clarification requests during a CoreAgent stream."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from soothe.sloop.clarification.protocol import ClarificationRequest

logger = logging.getLogger(__name__)


@dataclass
class ClarificationCapture:
    """First-wins capture of a clarification request emitted mid-stream.

    The CoreAgent stream wrapper writes here when it detects a structured
    ``ask_user`` interrupt. The originating loop node reads the captured
    request after the stream ends and threads it into
    ``pending_clarification`` so the graph router dispatches to
    ``await_clarification``.

    Attributes:
        pending_request: The first captured clarification request (None until set).
        resume_thread_id: The CoreAgent thread_id that was active when the
            interrupt fired. Set by the executor so the resume path can
            reuse it (``Command(resume=...)`` targets this thread).
    """

    pending_request: ClarificationRequest | None = None
    resume_thread_id: str | None = None

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


__all__ = ["ClarificationCapture"]
