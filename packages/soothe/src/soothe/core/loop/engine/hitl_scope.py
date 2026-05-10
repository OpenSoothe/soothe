"""Human-in-the-loop scope for CoreAgent streams under AgentLoop (RFC-221).

Interactive clients resolve LangGraph interrupts via the daemon runner's
``_interrupt_resolvers`` map. Executor streams run in the same asyncio task as
``SootheRunner.astream``, so we bind the active resolver with a `ContextVar`
without threading it through ``LoopRuntimeContext``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

_STREAM_POLL_INTERVAL_S = 0.5
_MAX_HITL_ITERATIONS = 50

HitlInterruptResolver = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_hitl_interrupt_resolver: contextvars.ContextVar[HitlInterruptResolver | None] = (
    contextvars.ContextVar("hitl_interrupt_resolver", default=None)
)


def get_hitl_interrupt_resolver() -> HitlInterruptResolver | None:
    """Return the async resolver for pending LangGraph interrupts, if any."""
    return _hitl_interrupt_resolver.get()


def set_hitl_interrupt_resolver_context(
    resolver: HitlInterruptResolver | None,
) -> contextvars.Token[HitlInterruptResolver | None] | None:
    """Bind a resolver for nested CoreAgent streams; returns token for reset."""
    if resolver is None:
        return None
    return _hitl_interrupt_resolver.set(resolver)


def reset_hitl_interrupt_resolver_context(
    token: contextvars.Token[HitlInterruptResolver | None] | None,
) -> None:
    """Reset the resolver binding from `set_hitl_interrupt_resolver_context`."""
    if token is not None:
        _hitl_interrupt_resolver.reset(token)


async def await_next_graph_stream_chunk(chunk_iter: AsyncIterator[Any]) -> Any:
    """Wait for the next graph chunk with periodic cooperative cancellation checks.

    Matches runner ``_await_next_astream_chunk`` so long gaps between tokens do
    not corrupt the iterator (IG-193).
    """
    anext_task = asyncio.create_task(chunk_iter.__anext__())
    try:
        while not anext_task.done():
            await asyncio.wait({anext_task}, timeout=_STREAM_POLL_INTERVAL_S)
            if anext_task.done():
                break
            current_task = asyncio.current_task()
            if current_task and current_task.cancelling():
                logger.info("CoreAgent HITL stream: cancellation request, stopping graph read")
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


def auto_approve_interrupt_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Build a LangGraph ``Command(resume=...)`` payload that approves all interrupts."""
    payload: dict[str, Any] = {}
    for iid, value in pending_interrupts.items():
        if isinstance(value, dict) and value.get("type") == "ask_user":
            questions = value.get("questions", [])
            payload[iid] = {"answers": ["" for _ in questions]}
        else:
            action_requests = []
            if isinstance(value, dict):
                action_requests = value.get("action_requests", [])
            decisions = [{"type": "approve"} for _ in (action_requests or [value])]
            payload[iid] = {"decisions": decisions}
    return payload


def _first_choice_value_for_ask_question(question: Any) -> str:
    """Pick the default answer for one ask_user question (first choice value, else empty)."""
    if not isinstance(question, dict):
        return ""
    choices = question.get("choices")
    if isinstance(choices, list) and len(choices) > 0:
        c0 = choices[0]
        if isinstance(c0, dict):
            raw = c0.get("value", "")
            return str(raw) if raw is not None else ""
    return ""


def timeout_default_hitl_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Resume payload when HITL wait times out: approve tools; ask_user uses first listed choice per question."""
    payload: dict[str, Any] = {}
    for iid, value in pending_interrupts.items():
        if isinstance(value, dict) and value.get("type") == "ask_user":
            questions = value.get("questions") or []
            if isinstance(questions, list):
                answers = [_first_choice_value_for_ask_question(q) for q in questions]
            else:
                answers = []
            payload[iid] = {"answers": answers}
        else:
            sub = auto_approve_interrupt_resume_payload({iid: value})
            payload[iid] = sub[iid]
    return payload


__all__ = [
    "HitlInterruptResolver",
    "_MAX_HITL_ITERATIONS",
    "auto_approve_interrupt_resume_payload",
    "timeout_default_hitl_resume_payload",
    "await_next_graph_stream_chunk",
    "get_hitl_interrupt_resolver",
    "reset_hitl_interrupt_resolver_context",
    "set_hitl_interrupt_resolver_context",
]
