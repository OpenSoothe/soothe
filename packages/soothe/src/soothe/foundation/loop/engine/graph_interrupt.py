"""LangGraph interrupt detection and auto-resume for CoreAgent streams.

Action-approval interrupts (deepagents tool review) are auto-approved here.
``ask_user`` interrupts are no longer handled in this module — they bubble up
through :class:`ClarificationCapture` to the ``await_clarification`` loop node
(RFC-622).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

logger = logging.getLogger(__name__)

_STREAM_POLL_INTERVAL_S = 0.5
_MAX_INTERRUPT_ITERATIONS = 50


async def await_next_graph_stream_chunk(chunk_iter: AsyncIterator[Any]) -> Any:
    """Wait for the next graph chunk with cooperative cancellation checks.

    IG-506: Timeout removed - LLMRateLimitMiddleware handles all LLM timeouts.

    This function only ensures:
    - Cooperative cancellation propagation (polls every 0.5s)
    - Clean iterator cleanup on cancellation

    LLM API timeout/retry is handled by LLMRateLimitMiddleware which wraps
    each individual LLM call. There is no chunk-level timeout here because:
    - Middleware already has configurable timeout + retry with escalation
    - A chunk timeout would race against middleware and cut off retries mid-way
    - Long gaps between LLM tokens do not corrupt the iterator (IG-193)

    Args:
        chunk_iter: Async iterator yielding graph stream chunks.

    Raises:
        asyncio.CancelledError: When the parent task is cancelled.
        StopAsyncIteration: When the iterator is exhausted.

    Note:
        The poll interval (0.5s) is for cooperative cancellation checks only.
        There is NO deadline-based timeout - middleware handles LLM stalls.
    """
    anext_task = asyncio.create_task(chunk_iter.__anext__())
    try:
        while not anext_task.done():
            await asyncio.wait({anext_task}, timeout=_STREAM_POLL_INTERVAL_S)
            if anext_task.done():
                break

            # Cooperative cancellation check
            current_task = asyncio.current_task()
            if current_task and current_task.cancelling():
                logger.info("CoreAgent stream: cancellation request, stopping graph read")
                anext_task.cancel()
                try:
                    await anext_task
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError

        return anext_task.result()
    finally:
        if not anext_task.done():
            anext_task.cancel()
            try:
                await anext_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass


def is_ask_user_interrupt(value: Any) -> bool:
    """Return True if ``value`` is a structured ``ask_user`` interrupt payload."""
    return isinstance(value, Mapping) and value.get("type") == "ask_user"


def build_auto_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Build a LangGraph ``Command(resume=...)`` payload that auto-approves tool interrupts.

    ``ask_user`` interrupts are intentionally skipped — those flow through the
    clarification relay (RFC-622) and must be answered by the policy layer,
    not auto-resumed here.
    """
    payload: dict[str, Any] = {}
    for iid, value in pending_interrupts.items():
        if is_ask_user_interrupt(value):
            continue
        action_requests = []
        if isinstance(value, dict):
            action_requests = value.get("action_requests", [])
        decisions = [{"type": "approve"} for _ in (action_requests or [value])]
        payload[iid] = {"decisions": decisions}
    return payload


__all__ = [
    "_MAX_INTERRUPT_ITERATIONS",
    "await_next_graph_stream_chunk",
    "build_auto_resume_payload",
    "is_ask_user_interrupt",
]
