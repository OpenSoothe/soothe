"""Cooperative vs unexpected stream cancellation policy.

User / daemon cancel sets a ``cancel_event`` and may cancel the stream task.
Libraries (LLM/httpx/anyio) can also raise ``asyncio.CancelledError`` without
that signal. Treating those as user cancel interrupts the loop incorrectly
(goal_interrupted, stream.end reason=cancelled, TUI cancel UX).

This helper:
- Cancels the stream task only when ``cancel_event`` is set (and logs it).
- Retries the stream once when ``CancelledError`` arrives without ``cancel_event``.
- Surfaces exhausted unexpected cancels as ``RuntimeError`` (error terminal),
  never as a cooperative cancel.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)

# One automatic retry absorbs transient internal CancelledError (e.g. mid-LLM hop).
_DEFAULT_UNEXPECTED_CANCEL_RETRIES = 1
_DEFAULT_POLL_INTERVAL_S = 0.25
_UNEXPECTED_CANCEL_ERROR_MSG = (
    "Agent stream hit an unexpected cancellation; the loop was not user-cancelled"
)


class _CancelFlag(Protocol):
    def is_set(self) -> bool: ...


async def await_cancellable_stream(
    stream_factory: Callable[[], Awaitable[None]],
    *,
    cancel_event: _CancelFlag,
    worker_id: str,
    loop_id: str,
    request_id: str,
    unexpected_retries: int = _DEFAULT_UNEXPECTED_CANCEL_RETRIES,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Run ``stream_factory`` with cancel-event polling and unexpected-cancel retry.

    Args:
        stream_factory: Zero-arg factory returning the stream awaitable (fresh
            each attempt so retries do not reuse a completed coroutine).
        cancel_event: Cooperative cancel flag from the pool (``threading.Event``
            or multiprocessing equivalent).
        worker_id: Worker id for logs.
        loop_id: Client loop id for logs.
        request_id: Request id for logs.
        unexpected_retries: Extra attempts after unexpected ``CancelledError``.
        poll_interval_s: How often to check ``cancel_event``.

    Raises:
        asyncio.CancelledError: When ``cancel_event`` is set (cooperative cancel).
        RuntimeError: When unexpected ``CancelledError`` retries are exhausted.
    """
    attempts = 1 + max(0, int(unexpected_retries))
    for attempt in range(1, attempts + 1):
        stream_task = asyncio.create_task(stream_factory())

        async def _poll_cancel_event(
            task: asyncio.Task[None] = stream_task,
        ) -> None:
            try:
                while True:
                    await asyncio.sleep(poll_interval_s)
                    if cancel_event.is_set():
                        logger.info(
                            "Worker %s: cancel_event set; cancelling stream loop=%s request_id=%s",
                            worker_id,
                            loop_id,
                            request_id,
                        )
                        task.cancel()
                        return
            except asyncio.CancelledError:
                raise

        poll_task = asyncio.create_task(_poll_cancel_event())
        try:
            await stream_task
            return
        except asyncio.CancelledError:
            if cancel_event.is_set():
                raise
            if attempt < attempts:
                logger.warning(
                    "Worker %s: unexpected CancelledError loop=%s request_id=%s; "
                    "retrying stream (attempt %d/%d) without interrupting the loop",
                    worker_id,
                    loop_id,
                    request_id,
                    attempt + 1,
                    attempts,
                    exc_info=True,
                )
                continue
            logger.error(
                "Worker %s: unexpected CancelledError loop=%s request_id=%s; "
                "retries exhausted — surfacing as stream error (not user cancel)",
                worker_id,
                loop_id,
                request_id,
                exc_info=True,
            )
            raise RuntimeError(_UNEXPECTED_CANCEL_ERROR_MSG) from None
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


def emit_terminal_for_cancelled_error(
    *,
    cancel_event: _CancelFlag,
    emit_cancelled: Callable[[], None],
    emit_error: Callable[[BaseException], None],
    worker_id: str,
    loop_id: str,
    request_id: str,
    where: str,
) -> None:
    """Map a leaked ``CancelledError`` to cancelled vs error terminal.

    Args:
        cancel_event: Cooperative cancel flag.
        emit_cancelled: Emit cooperative cancel terminal.
        emit_error: Emit error terminal with the given exception.
        worker_id: Worker id for logs.
        loop_id: Loop id for logs.
        request_id: Request id for logs.
        where: Short site label for logs (e.g. ``_execute``, ``run_until_complete``).
    """
    if cancel_event.is_set():
        logger.warning(
            "Worker %s: cooperative CancelledError at %s loop=%s request_id=%s",
            worker_id,
            where,
            loop_id,
            request_id,
        )
        emit_cancelled()
        return
    logger.error(
        "Worker %s: unexpected CancelledError at %s loop=%s request_id=%s; "
        "emitting error (not cancel) so the loop is not interrupted",
        worker_id,
        where,
        loop_id,
        request_id,
        exc_info=True,
    )
    emit_error(RuntimeError(_UNEXPECTED_CANCEL_ERROR_MSG))


__all__ = [
    "await_cancellable_stream",
    "emit_terminal_for_cancelled_error",
]
