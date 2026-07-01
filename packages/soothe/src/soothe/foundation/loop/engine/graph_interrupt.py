"""LangGraph interrupt detection and auto-resume for CoreAgent streams.

Action-approval interrupts (deepagents tool review) are auto-approved here.
``ask_user`` interrupts are no longer handled in this module — they bubble up
through :class:`ClarificationCapture` to the ``await_clarification`` loop node
(RFC-622).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

logger = logging.getLogger(__name__)

_STREAM_POLL_INTERVAL_S = 0.5
_MAX_INTERRUPT_ITERATIONS = 50

# Default inactivity timeout for graph stream chunks (seconds).
# When no chunk arrives within this window, the stream is considered stalled
# (typically a tool-dispatch hang in the LangGraph runtime) and a
# ``DispatchTimeoutError`` is raised so the step fails gracefully instead of
# hanging indefinitely. Set to 0 to disable.
_DEFAULT_DISPATCH_TIMEOUT_S: float = 300.0


class DispatchTimeoutError(Exception):
    """Raised when the graph stream stalls between chunks beyond a deadline.

    This covers the gap between LLM response capture and tool dispatch — a
    phase not covered by ``LLMRateLimitMiddleware`` (which only wraps the LLM
    HTTP call). When the LangGraph runtime stalls scheduling a tool_call, no
    stream chunks are produced, and this watchdog fires.

    Attributes:
        timeout_seconds: The inactivity threshold that was exceeded.
        step_id: Optional step identifier for correlation.
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        step_id: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.step_id = step_id
        loc = f" (step={step_id})" if step_id else ""
        super().__init__(
            f"Graph stream dispatch stalled: no chunks for {timeout_seconds:.1f}s{loc}. "
            f"This indicates a tool-dispatch hang in the graph runtime."
        )


async def await_next_graph_stream_chunk(
    chunk_iter: AsyncIterator[Any],
    *,
    dispatch_timeout: float | None = None,
    step_id: str | None = None,
) -> Any:
    """Wait for the next graph chunk with cooperative cancellation and watchdog.

    Behavior:
    - Cooperative cancellation: polls every ``_STREAM_POLL_INTERVAL_S`` and
      propagates ``asyncio.CancelledError`` when the parent task is cancelled.
    - Dispatch watchdog: when ``dispatch_timeout`` > 0, raises
      :class:`DispatchTimeoutError` if no chunk arrives within the deadline.
      This catches stalls in the LangGraph runtime between LLM response and
      tool dispatch — a gap not covered by LLM middleware timeouts.

    LLM API timeout/retry is handled by ``LLMRateLimitMiddleware`` which wraps
    each individual LLM call. The dispatch watchdog here is complementary: it
    covers the post-LLM phase where the graph runtime schedules tool execution.
    A chunk timeout does not race against middleware because middleware
    timeouts fire during the LLM HTTP call (chunks are flowing), while the
    watchdog fires when chunks stop (dispatch has stalled).

    Args:
        chunk_iter: Async iterator yielding graph stream chunks.
        dispatch_timeout: Inactivity timeout in seconds. ``None`` or ``0``
            disables the watchdog (preserves backward compatibility). When
            positive, raises :class:`DispatchTimeoutError` if no chunk arrives
            within this window.
        step_id: Optional step identifier for diagnostic logging.

    Raises:
        asyncio.CancelledError: When the parent task is cancelled.
        StopAsyncIteration: When the iterator is exhausted.
        DispatchTimeoutError: When no chunk arrives within ``dispatch_timeout``.

    Note:
        The poll interval (0.5s) is for cooperative cancellation checks only.
        The watchdog deadline is separate and tracks wall-clock inactivity.
    """
    anext_task = asyncio.create_task(chunk_iter.__anext__())
    watchdog_start = time.perf_counter()
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

            # Dispatch watchdog: check for inactivity stall
            if dispatch_timeout and dispatch_timeout > 0:
                elapsed = time.perf_counter() - watchdog_start
                if elapsed >= dispatch_timeout:
                    logger.warning(
                        "CoreAgent stream dispatch watchdog: no chunks for %.1fs%s, "
                        "cancelling stream read",
                        elapsed,
                        f" (step={step_id})" if step_id else "",
                    )
                    anext_task.cancel()
                    try:
                        await anext_task
                    except (asyncio.CancelledError, StopAsyncIteration):
                        pass
                    raise DispatchTimeoutError(dispatch_timeout, step_id=step_id)

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
    "_DEFAULT_DISPATCH_TIMEOUT_S",
    "_MAX_INTERRUPT_ITERATIONS",
    "await_next_graph_stream_chunk",
    "build_auto_resume_payload",
    "DispatchTimeoutError",
    "is_ask_user_interrupt",
]
