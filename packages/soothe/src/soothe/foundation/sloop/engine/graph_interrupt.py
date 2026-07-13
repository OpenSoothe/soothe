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

# IG-549: Heartbeat interval for long-running tool execution.
# When no chunks arrive for this duration, emit a heartbeat event to keep
# the stream alive and prevent client disconnects.
_STREAM_HEARTBEAT_INTERVAL_S = 10.0

# When no chunk arrives within this window, the stream is considered stalled
# (typically a tool-dispatch hang in the LangGraph runtime) and a
# ``DispatchTimeoutError`` is raised so the step fails gracefully instead of
# hanging indefinitely. Set to 0 to disable. Configure via
# ``agent.loop.dispatch_timeout_seconds`` (default: 0 = disabled).


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


class GraphStreamChunkReader:
    """Persistent async-iterator reader for CoreAgent graph streams.

    Keeps a single pending ``__anext__()`` task alive across IG-549 heartbeat
    sentinels so long-running tool/subagent execution is not aborted when the
    client receives keep-alive events.
    """

    def __init__(
        self,
        chunk_iter: AsyncIterator[Any],
        *,
        dispatch_timeout: float | None = None,
        step_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> None:
        self._chunk_iter = chunk_iter
        self._dispatch_timeout = dispatch_timeout
        self._step_id = step_id
        self._heartbeat_interval = heartbeat_interval or _STREAM_HEARTBEAT_INTERVAL_S
        self._pending: asyncio.Task[Any] | None = None
        self._watchdog_start = time.perf_counter()
        self._heartbeat_start = time.perf_counter()

    def _ensure_pending(self) -> asyncio.Task[Any]:
        if self._pending is None:
            self._pending = asyncio.create_task(self._chunk_iter.__anext__())
        return self._pending

    async def _cancel_pending(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is None or pending.done():
            return
        pending.cancel()
        try:
            await pending
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    async def read_next(self) -> Any:
        """Return the next chunk, a heartbeat sentinel, or raise ``StopAsyncIteration``."""
        anext_task = self._ensure_pending()
        try:
            while not anext_task.done():
                await asyncio.wait({anext_task}, timeout=_STREAM_POLL_INTERVAL_S)
                if anext_task.done():
                    break

                current_task = asyncio.current_task()
                if current_task and current_task.cancelling():
                    logger.info("CoreAgent stream: cancellation request, stopping graph read")
                    await self._cancel_pending()
                    raise asyncio.CancelledError

                if self._dispatch_timeout and self._dispatch_timeout > 0:
                    elapsed = time.perf_counter() - self._watchdog_start
                    if elapsed >= self._dispatch_timeout:
                        logger.warning(
                            "CoreAgent stream dispatch watchdog: no chunks for %.1fs%s, "
                            "cancelling stream read",
                            elapsed,
                            f" (step={self._step_id})" if self._step_id else "",
                        )
                        await self._cancel_pending()
                        raise DispatchTimeoutError(self._dispatch_timeout, step_id=self._step_id)

                heartbeat_elapsed = time.perf_counter() - self._heartbeat_start
                if heartbeat_elapsed >= self._heartbeat_interval:
                    logger.debug(
                        "CoreAgent stream heartbeat: no chunks for %.1fs%s, emitting sentinel",
                        heartbeat_elapsed,
                        f" (step={self._step_id})" if self._step_id else "",
                    )
                    self._heartbeat_start = time.perf_counter()
                    return _STREAM_HEARTBEAT_SENTINEL

            try:
                return anext_task.result()
            finally:
                self._pending = None
                self._watchdog_start = time.perf_counter()
                self._heartbeat_start = time.perf_counter()
        except StopAsyncIteration:
            self._pending = None
            raise

    async def cancel(self) -> None:
        """Cancel any pending ``__anext__()`` and close the stream read."""
        await self._cancel_pending()


async def await_next_graph_stream_chunk(
    chunk_iter: AsyncIterator[Any],
    *,
    dispatch_timeout: float | None = None,
    step_id: str | None = None,
    heartbeat_interval: float | None = None,
) -> Any:
    """Wait for the next graph chunk with cooperative cancellation and watchdog.

    Prefer :class:`GraphStreamChunkReader` when consuming multiple chunks from
    the same iterator — this helper creates a one-shot reader and must not be
    called repeatedly across heartbeat sentinels on the same ``chunk_iter``.

    Behavior:
    - Cooperative cancellation: polls every ``_STREAM_POLL_INTERVAL_S`` and
      propagates ``asyncio.CancelledError`` when the parent task is cancelled.
    - Dispatch watchdog: when ``dispatch_timeout`` > 0, raises
      :class:`DispatchTimeoutError` if no chunk arrives within the deadline.
      This catches stalls in the LangGraph runtime between LLM response and
      tool dispatch — a gap not covered by LLM middleware timeouts.
    - Heartbeat sentinel: IG-549 when ``heartbeat_interval`` > 0, returns
      ``_STREAM_HEARTBEAT_SENTINEL`` instead of raising if no chunk arrives
      within the heartbeat window. This keeps the stream alive during long
      tool execution (browser_use, web searches) without dropping events.

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
        heartbeat_interval: IG-549 Interval in seconds for heartbeat sentinel
            emission. When no chunk arrives within this window, returns
            ``_STREAM_HEARTBEAT_SENTINEL`` to signal stream is still alive.
            Default: ``_STREAM_HEARTBEAT_INTERVAL_S`` (10s).

    Raises:
        asyncio.CancelledError: When the parent task is cancelled.
        StopAsyncIteration: When the iterator is exhausted.
        DispatchTimeoutError: When no chunk arrives within ``dispatch_timeout``
            and heartbeat mode is not enabled.

    Note:
        The poll interval (0.5s) is for cooperative cancellation checks only.
        The watchdog deadline is separate and tracks wall-clock inactivity.
    """
    reader = GraphStreamChunkReader(
        chunk_iter,
        dispatch_timeout=dispatch_timeout,
        step_id=step_id,
        heartbeat_interval=heartbeat_interval,
    )
    try:
        return await reader.read_next()
    finally:
        await reader.cancel()


# IG-549: Sentinel object returned when heartbeat interval elapses without a chunk.
# Executor consumes this and can optionally emit a step_progress event.
_STREAM_HEARTBEAT_SENTINEL = object()


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
    "_STREAM_HEARTBEAT_INTERVAL_S",
    "_STREAM_HEARTBEAT_SENTINEL",
    "GraphStreamChunkReader",
    "await_next_graph_stream_chunk",
    "build_auto_resume_payload",
    "DispatchTimeoutError",
    "is_ask_user_interrupt",
]
