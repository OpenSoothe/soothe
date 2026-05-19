"""LangGraph interrupt detection and auto-resume for CoreAgent streams."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

logger = logging.getLogger(__name__)

_STREAM_POLL_INTERVAL_S = 0.5
_MAX_INTERRUPT_ITERATIONS = 50


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


def build_auto_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Build a LangGraph ``Command(resume=...)`` payload that auto-continues all interrupts."""
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


__all__ = [
    "_MAX_INTERRUPT_ITERATIONS",
    "await_next_graph_stream_chunk",
    "build_auto_resume_payload",
]
