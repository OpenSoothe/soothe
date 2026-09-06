"""Park: transition a captured clarification to the waiting state.

Manual mode: the interactive policy returns `defer=True` with
`defer_kind="manual"` — the goal is marked `awaiting_clarification` and the
graph exits cleanly (no StrangeLoop `interrupt()`).

Auto mode: the policy resolves inline. On success, the answer is stored and
the execute node can resume immediately. On failure, the goal parks.

Retry circuit breaker: when the auto policy returns `source="retry"`, the
per-goal retry count is checked. Exceeding the cap fails the goal with
`defer_kind="retry_limit"`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    ClarificationPolicy,
)
from soothe.sloop.relay.store import ClarificationStore, encode_answer
from soothe.sloop.relay.types import ParkOutcome, RelayHandle

logger = logging.getLogger(__name__)

_EmitFn = Any
"""Emit callback: `async def emit(event_type: str, payload: dict) -> None`."""


class _CEProtocol(Protocol):
    async def mark_awaiting_clarification(
        self, goal_id: str, pending: dict[str, Any] | None, *, reason: str = ...
    ) -> None: ...


async def park_clarification(
    store: ClarificationStore,
    handle: RelayHandle,
    *,
    policy: ClarificationPolicy | None,
    ce: _CEProtocol | None = None,
    emit: _EmitFn | None = None,
    plan_path: str | None = None,
    plan_markdown: str | None = None,
    max_consecutive_retries: int = 5,
) -> ParkOutcome:
    """Park a captured clarification for human or auto resolution.

    Returns a `ParkOutcome` indicating whether the clarification was answered
    inline (auto), parked for a human (manual), or deferred.
    """
    relay_id = handle.relay_id
    request = handle.request
    parked_at = datetime.now(UTC).isoformat()

    if policy is None:
        await _defer(
            store,
            relay_id,
            ce=ce,
            emit=emit,
            reason="no policy configured",
            defer_kind="explicit",
            parked_at=parked_at,
            pending=request_to_pending_dict(handle),
            goal_id=request.loop_state.goal_id,
        )
        return ParkOutcome(kind="deferred", relay_id=relay_id, defer_kind="explicit")

    if emit is not None:
        payload: dict[str, Any] = {
            "questions": list(request.questions),
            "origin_node": request.origin_node,
            "relay_id": relay_id,
            "step_id": handle.step_id or "",
        }
        if plan_path:
            payload["plan_path"] = plan_path
        if plan_markdown:
            payload["plan_markdown"] = plan_markdown
        await emit("clarification_requested", payload)

    try:
        answer = await policy.answer(request)
    except ClarificationDeferredError as exc:
        await _defer(
            store,
            relay_id,
            ce=ce,
            emit=emit,
            reason=exc.reason,
            defer_kind=exc.kind,
            parked_at=parked_at,
            pending=request_to_pending_dict(handle),
            goal_id=request.loop_state.goal_id,
        )
        return ParkOutcome(kind="deferred", relay_id=relay_id, defer_kind=exc.kind)

    if answer.defer:
        defer_kind = str(answer.audit.get("defer_kind", "explicit"))
        is_manual = defer_kind == "manual"
        await store.update(relay_id, status="parked", parked_at=parked_at, defer_kind=defer_kind)
        if ce is not None:
            try:
                await ce.mark_awaiting_clarification(
                    request.loop_state.goal_id,
                    request_to_pending_dict(handle),
                    reason=defer_kind,
                )
            except Exception:
                logger.warning("[Relay] CE mark failed (relay=%s)", relay_id[:12], exc_info=True)
        if emit is not None and not is_manual:
            await emit(
                "clarification_deferred",
                {
                    "reason": str(answer.audit.get("reason", "deferred")),
                    "defer_kind": defer_kind,
                    "relay_id": relay_id,
                },
            )
        outcome_kind = "awaiting_human" if is_manual else "deferred"
        return ParkOutcome(
            kind=outcome_kind,  # type: ignore[arg-type]
            relay_id=relay_id,
            defer_kind=defer_kind,  # type: ignore[arg-type]
        )

    # Retry circuit breaker.
    if answer.source == "retry":
        retry_count = await store.count_retries_by_goal(request.loop_state.goal_id)
        if retry_count >= max_consecutive_retries:
            await store.update(relay_id, status="failed", defer_kind="retry_limit")
            if emit is not None:
                await emit(
                    "clarification_deferred",
                    {
                        "reason": f"circuit breaker: {retry_count}/{max_consecutive_retries}",
                        "defer_kind": "retry_limit",
                        "relay_id": relay_id,
                    },
                )
            logger.warning(
                "[Relay] circuit breaker relay_id=%s retries=%d/%d",
                relay_id[:12],
                retry_count,
                max_consecutive_retries,
            )
            return ParkOutcome(kind="deferred", relay_id=relay_id, defer_kind="retry_limit")

    # Auto success — store inline.
    await store.update(
        relay_id,
        status="answered",
        answer_json=encode_answer(answer),
        answer_source=answer.source,
        answered_at=datetime.now(UTC).isoformat(),
    )
    if emit is not None:
        await emit(
            "clarification_answered",
            {
                "source": answer.source,
                "confidence": answer.confidence,
                "defer": False,
                "relay_id": relay_id,
            },
        )
    logger.info("[Relay] answered relay_id=%s source=%s", relay_id[:12], answer.source)
    return ParkOutcome(kind="answered", relay_id=relay_id, answer=answer)


def request_to_pending_dict(handle: RelayHandle) -> dict[str, Any]:
    """Build a minimal `pending_clarification` dict for CE projection."""
    return {
        "origin_node": handle.origin,
        "origin_interrupt_id": handle.request.origin_interrupt_id,
        "relay_id": handle.relay_id,
        "questions": list(handle.request.questions),
    }


async def _defer(
    store: ClarificationStore,
    relay_id: str,
    *,
    ce: _CEProtocol | None,
    emit: _EmitFn | None,
    reason: str,
    defer_kind: str,
    parked_at: str,
    pending: dict[str, Any],
    goal_id: str,
) -> None:
    await store.update(relay_id, status="parked", parked_at=parked_at, defer_kind=defer_kind)
    if ce is not None:
        try:
            await ce.mark_awaiting_clarification(goal_id, pending, reason=defer_kind)
        except Exception:
            logger.warning("[Relay] CE mark failed (relay=%s)", relay_id[:12], exc_info=True)
    if emit is not None:
        await emit(
            "clarification_deferred",
            {"reason": reason, "defer_kind": defer_kind, "relay_id": relay_id},
        )


__all__ = ["park_clarification", "request_to_pending_dict"]
