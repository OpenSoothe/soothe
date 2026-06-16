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

# Default timeout for waiting on a single stream chunk when no LLM rate limit middleware.
# Prevents indefinite hangs on unresponsive LLM API calls.
_DEFAULT_CHUNK_TIMEOUT_S = 120.0


async def await_next_graph_stream_chunk(
    chunk_iter: AsyncIterator[Any],
    chunk_timeout_s: float = _DEFAULT_CHUNK_TIMEOUT_S,
) -> Any:
    """Wait for the next graph chunk with timeout and cooperative cancellation checks.

    Matches runner ``_await_next_astream_chunk`` so long gaps between tokens do
    not corrupt the iterator (IG-193).

    Args:
        chunk_iter: Async iterator yielding graph stream chunks.
        chunk_timeout_s: Maximum seconds to wait for a chunk before raising TimeoutError.
            Defaults to 120s (fallback when LLM rate limit middleware is disabled).

    Raises:
        TimeoutError: When no chunk received within chunk_timeout_s.
        asyncio.CancelledError: When the parent task is cancelled.
    """
    anext_task = asyncio.create_task(chunk_iter.__anext__())
    deadline = asyncio.get_event_loop().time() + chunk_timeout_s
    try:
        while not anext_task.done():
            # Check remaining time before wait
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(
                    "CoreAgent stream chunk timeout (%ds) - no response from LLM",
                    int(chunk_timeout_s),
                )
                anext_task.cancel()
                try:
                    await anext_task
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
                raise TimeoutError(
                    f"LLM stream chunk timeout after {int(chunk_timeout_s)}s - "
                    "no response received. Check LLM API connectivity or enable "
                    "llm_rate_limit middleware for configurable timeouts."
                )

            # Wait for either task completion or poll interval
            wait_time = min(_STREAM_POLL_INTERVAL_S, remaining)
            await asyncio.wait({anext_task}, timeout=wait_time)
            if anext_task.done():
                break
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
