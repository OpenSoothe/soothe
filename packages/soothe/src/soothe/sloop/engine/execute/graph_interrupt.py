"""LangGraph interrupt detection and auto-resume for CoreAgent streams.

Action-approval interrupts (soothe_deepagents tool review) and ``ask_user``
interrupts both bubble up through :class:`ClarificationCapture` to the
``await_clarification`` loop node (RFC-622). This module owns the resume-payload
translators that turn a clarified answer back into the ``Command(resume=...)``
shape each origin's middleware expects.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from soothe_sdk.ux.execute_namespace import is_step_level_execute_namespace_key

from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationRequest,
)

logger = logging.getLogger(__name__)

_STREAM_POLL_INTERVAL_S = 0.5
_MAX_INTERRUPT_ITERATIONS = 50

# Heartbeat interval for long-running tool execution.
# When no chunks arrive for this duration, emit a heartbeat event to keep
# the stream alive and prevent client disconnects.
_STREAM_HEARTBEAT_INTERVAL_S = 10.0

# Secondary safety net — max heartbeat sentinels emitted while no
# root-level tool is active. At the default 10s heartbeat interval,
# 360 sentinels = 1 hour of inactivity. Suspended while tools are active
# so long-running tools (task, browser_use, Gradle) are not killed; those
# are bounded by agent.middleware.tool_timeout instead.
_MAX_HEARTBEAT_SENTINELS = 360

ChunkKind = Literal["sentinel", "tool_dispatch", "tool_result", "chunk"]


@dataclass(frozen=True)
class StreamChunkClass:
    """Classification of one graph stream chunk for dispatch watchdogs."""

    kind: ChunkKind
    tool_call_ids: tuple[str, ...] = field(default_factory=tuple)
    result_tool_call_id: str | None = None


# Sentinel object returned when heartbeat interval elapses without a chunk.
# Executor consumes this and can optionally emit a step_progress event.
_STREAM_HEARTBEAT_SENTINEL = object()


class DispatchTimeoutError(Exception):
    """Raised when the graph stream stalls between chunks beyond a deadline.

    This covers the gap between LLM response capture and tool dispatch — a
    phase not covered by ``LLMRateLimitMiddleware`` (which only wraps the LLM
    HTTP call). When the LangGraph runtime stalls scheduling a tool_call, no
    stream chunks are produced, and this watchdog fires.

    Attributes:
        timeout_seconds: The inactivity threshold that was exceeded.
        step_id: Optional step identifier for correlation.
        reason: What kind of timeout fired (``"idle"``, ``"tool_wall_clock"``,
            ``"sentinel_cap"``).
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        step_id: str | None = None,
        reason: str = "idle",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.step_id = step_id
        self.reason = reason
        loc = f" (step={step_id})" if step_id else ""
        if reason == "tool_wall_clock":
            msg = (
                f"Tool execution exceeded wall-clock cap of {timeout_seconds:.1f}s{loc}. "
                f"The tool was active but produced no stream chunks within the deadline."
            )
        elif reason == "sentinel_cap":
            msg = (
                f"Heartbeat sentinel cap reached ({timeout_seconds:.1f}s of inactivity){loc}. "
                f"The stream produced no real chunks within the sentinel safety limit."
            )
        else:
            msg = (
                f"Graph stream dispatch stalled: no chunks for {timeout_seconds:.1f}s{loc}. "
                f"This indicates a deadlock between tool result and next LLM call."
            )
        super().__init__(msg)


def _is_root_stream_namespace(namespace: Any) -> bool:
    """True for main-graph / step-level namespaces (not nested subgraph tools).

    Empty ``()`` is treated as root (common in unit tests and some stream
    shapes). Step-level ``execute:*`` namespaces (including parallel branches)
    are root for watchdog purposes. Nested ``tools:*`` subgraphs are not.
    """
    if not namespace:
        return True
    if not isinstance(namespace, tuple):
        return False
    return is_step_level_execute_namespace_key(namespace)


def _tool_call_id_from_item(item: Any) -> str | None:
    if isinstance(item, Mapping):
        tid = item.get("id")
    else:
        tid = getattr(item, "id", None)
    if tid is None:
        return None
    text = str(tid).strip()
    return text or None


def _extract_dispatch_tool_call_ids(msg: Any) -> tuple[str, ...]:
    """Collect unique tool_call ids from an AIMessage / AIMessageChunk."""
    seen: list[str] = []
    for tc in getattr(msg, "tool_calls", None) or []:
        tid = _tool_call_id_from_item(tc)
        if tid and tid not in seen:
            seen.append(tid)
    for tcc in getattr(msg, "tool_call_chunks", None) or []:
        tid = _tool_call_id_from_item(tcc)
        if tid and tid not in seen:
            seen.append(tid)
    return tuple(seen)


def _classify_stream_chunk(chunk: Any) -> StreamChunkClass:
    """Classify a stream chunk for tool-boundary and progress tracking.

    Root-namespace ``tool_dispatch`` / ``tool_result`` update the pending-tool
    set. Nested subgraph messages (and all other real chunks) are ``chunk`` —
    they reset idle/sentinel clocks but do not clear parent tool activity.
    """
    if chunk is _STREAM_HEARTBEAT_SENTINEL:
        return StreamChunkClass(kind="sentinel")

    if not isinstance(chunk, tuple) or len(chunk) != 3:
        return StreamChunkClass(kind="chunk")

    namespace, mode, data = chunk
    is_root = _is_root_stream_namespace(namespace)

    if mode == "messages" and isinstance(data, (list, tuple)) and len(data) >= 1:
        msg = data[0]
        msg_type = type(msg).__name__
        if msg_type in ("AIMessage", "AIMessageChunk"):
            ids = _extract_dispatch_tool_call_ids(msg)
            tool_calls = getattr(msg, "tool_calls", None) or []
            tool_call_chunks = getattr(msg, "tool_call_chunks", None) or []
            if ids or tool_calls or tool_call_chunks:
                if is_root:
                    return StreamChunkClass(kind="tool_dispatch", tool_call_ids=ids)
                return StreamChunkClass(kind="chunk")
            return StreamChunkClass(kind="chunk")
        if msg_type == "ToolMessage":
            if is_root:
                result_id = getattr(msg, "tool_call_id", None)
                result_text = str(result_id).strip() if result_id is not None else ""
                return StreamChunkClass(
                    kind="tool_result",
                    result_tool_call_id=result_text or None,
                )
            return StreamChunkClass(kind="chunk")
        return StreamChunkClass(kind="chunk")

    return StreamChunkClass(kind="chunk")


class GraphStreamChunkReader:
    """Persistent async-iterator reader for CoreAgent graph streams.

    Keeps a single pending ``__anext__`` task alive across heartbeat
    sentinels so long-running tool/subagent execution is not aborted when the
    client receives keep-alive events.

    Tool-aware inactivity tracking:

    - **Idle timer** (``idle_timeout``): resets on every real chunk. Fires only
      when no root-level tools are pending — the deadlock gap after the last
      ToolMessage before the next LLM hop.
    - **Tool wall-clock timer** (``tool_timeout``): starts when the first root
      tool becomes pending, stops when the pending set empties. Optional; ``0``
      defers to ``agent.middleware.tool_timeout`` middleware.
    - **Pending-tool set**: root dispatches add tool_call ids; root ToolMessages
      remove them. Nested subgraph messages never clear parent activity.
    - **Sentinel cap**: applies only while no root tools are pending, so
      long-running tools are not killed by the idle safety net.
    """

    def __init__(
        self,
        chunk_iter: AsyncIterator[Any],
        *,
        idle_timeout: float | None = None,
        tool_timeout: float | None = None,
        step_id: str | None = None,
        heartbeat_interval: float | None = None,
        max_heartbeats: int | None = None,
    ) -> None:
        self._chunk_iter = chunk_iter
        self._step_id = step_id
        self._heartbeat_interval = heartbeat_interval or _STREAM_HEARTBEAT_INTERVAL_S
        self._pending: asyncio.Task[Any] | None = None

        self._idle_timeout = max(0.0, float(idle_timeout)) if idle_timeout else 0.0
        self._tool_timeout = max(0.0, float(tool_timeout)) if tool_timeout else 0.0
        self._max_heartbeats = (
            max(0, int(max_heartbeats)) if max_heartbeats is not None else _MAX_HEARTBEAT_SENTINELS
        )

        self._idle_start = time.perf_counter()
        self._heartbeat_start = time.perf_counter()
        self._pending_tool_ids: set[str] = set()
        self._anonymous_active = 0
        self._tool_wave_start: float | None = None
        self._heartbeat_sentinel_count = 0

    @property
    def _tools_active(self) -> bool:
        return bool(self._pending_tool_ids) or self._anonymous_active > 0

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

    def _reset_idle_timer(self) -> None:
        self._idle_start = time.perf_counter()

    def _note_tool_dispatch(self, tool_call_ids: tuple[str, ...]) -> None:
        """Record root tool dispatch ids (idempotent for streaming chunks)."""
        if tool_call_ids:
            self._pending_tool_ids.update(tool_call_ids)
            # Concrete ids replace any soft hold from id-less stream chunks.
            self._anonymous_active = 0
        else:
            # Streaming/partial dispatch without ids yet — keep a soft hold so
            # idle does not fire between the first tool_call_chunk and id fill.
            self._anonymous_active = max(self._anonymous_active, 1)
        if self._tools_active and self._tool_wave_start is None:
            self._tool_wave_start = time.perf_counter()

    def _note_tool_result(self, tool_call_id: str | None) -> None:
        """Clear one root tool result from the pending set."""
        if tool_call_id and tool_call_id in self._pending_tool_ids:
            self._pending_tool_ids.discard(tool_call_id)
        elif not self._pending_tool_ids and self._anonymous_active > 0:
            self._anonymous_active -= 1
        if not self._tools_active:
            self._tool_wave_start = None
            self._anonymous_active = 0

    def _apply_chunk_classification(self, classification: StreamChunkClass) -> None:
        if classification.kind == "sentinel":
            return
        self._reset_idle_timer()
        self._heartbeat_sentinel_count = 0
        if classification.kind == "tool_dispatch":
            self._note_tool_dispatch(classification.tool_call_ids)
        elif classification.kind == "tool_result":
            self._note_tool_result(classification.result_tool_call_id)

    def _check_watchdogs(self) -> DispatchTimeoutError | None:
        """Return an error if any watchdog threshold is exceeded, else None."""
        now = time.perf_counter()
        tools_active = self._tools_active

        if self._tool_timeout > 0 and self._tool_wave_start is not None and tools_active:
            tool_elapsed = now - self._tool_wave_start
            if tool_elapsed >= self._tool_timeout:
                return DispatchTimeoutError(
                    self._tool_timeout,
                    step_id=self._step_id,
                    reason="tool_wall_clock",
                )

        if self._idle_timeout > 0 and not tools_active:
            idle_elapsed = now - self._idle_start
            if idle_elapsed >= self._idle_timeout:
                return DispatchTimeoutError(
                    self._idle_timeout,
                    step_id=self._step_id,
                    reason="idle",
                )

        # Sentinel cap only when no root tools are pending — long tools rely on
        # middleware / optional tool_timeout instead of this idle safety net.
        if (
            not tools_active
            and self._max_heartbeats > 0
            and self._heartbeat_sentinel_count >= self._max_heartbeats
        ):
            return DispatchTimeoutError(
                self._heartbeat_sentinel_count * self._heartbeat_interval,
                step_id=self._step_id,
                reason="sentinel_cap",
            )

        return None

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

                error = self._check_watchdogs()
                if error is not None:
                    logger.warning(
                        "CoreAgent stream dispatch watchdog: %s%s, cancelling stream read",
                        error.reason,
                        f" (step={self._step_id})" if self._step_id else "",
                    )
                    await self._cancel_pending()
                    raise error

                heartbeat_elapsed = time.perf_counter() - self._heartbeat_start
                if heartbeat_elapsed >= self._heartbeat_interval:
                    self._heartbeat_sentinel_count += 1
                    logger.debug(
                        "CoreAgent stream heartbeat: no chunks for %.1fs%s, emitting sentinel",
                        heartbeat_elapsed,
                        f" (step={self._step_id})" if self._step_id else "",
                    )
                    self._heartbeat_start = time.perf_counter()
                    return _STREAM_HEARTBEAT_SENTINEL

            try:
                chunk = anext_task.result()
            finally:
                self._pending = None

            self._apply_chunk_classification(_classify_stream_chunk(chunk))
            return chunk
        except StopAsyncIteration:
            self._pending = None
            raise

    async def cancel(self) -> None:
        """Cancel any pending ``__anext__()`` and close the stream read."""
        await self._cancel_pending()


def is_ask_user_interrupt(value: Any) -> bool:
    """Return True if ``value`` is a structured ``ask_user`` interrupt payload."""
    return isinstance(value, Mapping) and value.get("type") == "ask_user"


def is_tool_approval_interrupt(value: Any) -> bool:
    """Return True if ``value`` is a deepagents ``action_requests`` interrupt.

    The ``HumanInTheLoopMiddleware`` emits this shape when a tool call matches
    an ``interrupt_on`` rule. These are captured into the clarification relay
    (``tool_approval`` origin) and resolved by the multi-stage pipeline
    (RFC-622 §9b) or veritas fallback — never auto-approved silently.
    """
    return isinstance(value, Mapping) and "action_requests" in value


def build_auto_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``Command(resume=...)`` payload for residual non-clarification interrupts.

    ``ask_user`` and ``action_requests`` (tool-approval) interrupts are
    captured by the clarification relay before this function runs; they never
    reach ``pending_interrupts``. This function auto-approves any *other*
    interrupt type that reached ``pending_interrupts`` — these are typically
    deepagents middleware interrupts unrelated to clarification.
    """
    payload: dict[str, Any] = {}
    for iid, value in pending_interrupts.items():
        if is_ask_user_interrupt(value) or is_tool_approval_interrupt(value):
            continue
        decisions = [{"type": "approve"}]
        payload[iid] = {"decisions": decisions}
    return payload


def build_tool_approval_resume_payload(
    interrupt_id: str,
    *,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the resume payload for a tool-approval interrupt.

    Translates the clarification relay's answer (approve/reject/edit per
    action request) into the ``{"decisions": [...]}`` shape the deepagents
    ``HumanInTheLoopMiddleware`` expects on ``Command(resume=...)``.
    """
    return {interrupt_id: {"decisions": decisions}}


# Mapping from a veritas/TUI tool-approval answer to the deepagents HITL
# decision type the ``HumanInTheLoopMiddleware`` expects on resume.
_APPROVE_TOKENS = frozenset({"approve", "yes", "ok", "allow", "accept", "proceed", "y"})
_REJECT_TOKENS = frozenset({"reject", "no", "deny", "block", "cancel", "n"})
_EDIT_TOKENS = frozenset({"edit", "modify", "change", "revise"})


def _answer_to_decision(answer: str) -> str:
    """Map a tool-approval answer string to a HITL ``DecisionType``.

    The clarification relay answers with a free-form string (from veritas or
    the TUI input). The deepagents middleware expects ``"approve"`` /
    ``"edit"`` / ``"reject"``. Defaults to ``"approve"`` for unrecognized
    positive-ish answers and ``"reject"`` only on an explicit reject token.
    """
    token = (answer or "").strip().lower()
    if token in _REJECT_TOKENS:
        return "reject"
    if token in _EDIT_TOKENS:
        return "edit"
    return "approve"


def build_clarification_resume_payload(
    request: ClarificationRequest,
    answer: ClarificationAnswer,
) -> dict[str, Any]:
    """Build the ``Command(resume=...)`` payload for a clarified interrupt.

    Single resume translator for every clarification origin:

    - ``tool_approval`` — map the relay's answer to a HITL ``decisions`` shape.
      One decision per pending action request (hanging tool call). The
      ``HumanInTheLoopMiddleware`` requires the decisions list length to match
      the number of hanging tool calls — a mismatch raises ``ValueError`` at
      resume time. When the answer has fewer entries than action requests,
      remaining slots default to the first answer (or ``"approve"``).
    - otherwise (``ask_user`` / execute) — deliver the answers verbatim so the
      ``ask_user`` tool returns the Q&A and the agent continues its turn.
    """
    if request.origin_node == ORIGIN_TOOL_APPROVAL:
        action_requests = request.metadata.get("action_requests", [])
        n_pending = (
            len(action_requests) if isinstance(action_requests, list) and action_requests else 0
        )
        answers = list(answer.answers) if answer.answers else ["approve"]
        # When action_requests metadata is unavailable, fall back to the
        # number of answers (one answer per pending tool call).
        if n_pending == 0:
            n_pending = len(answers) if answers else 1
        decisions: list[dict[str, Any]] = []
        for i in range(n_pending):
            ans = answers[i] if i < len(answers) else answers[0]
            decisions.append({"type": _answer_to_decision(ans)})
        return build_tool_approval_resume_payload(
            request.origin_interrupt_id,
            decisions=decisions,
        )
    return {request.origin_interrupt_id: {"answers": list(answer.answers)}}


__all__ = [
    "StreamChunkClass",
    "_MAX_HEARTBEAT_SENTINELS",
    "_MAX_INTERRUPT_ITERATIONS",
    "_STREAM_HEARTBEAT_INTERVAL_S",
    "_STREAM_HEARTBEAT_SENTINEL",
    "_classify_stream_chunk",
    "GraphStreamChunkReader",
    "_answer_to_decision",
    "build_auto_resume_payload",
    "build_clarification_resume_payload",
    "build_tool_approval_resume_payload",
    "DispatchTimeoutError",
    "is_ask_user_interrupt",
    "is_tool_approval_interrupt",
]
