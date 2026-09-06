"""Capture: detect and durably persist a clarification interrupt."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.protocol import LoopStateView
from soothe.sloop.relay.errors import RelayQueueFullError
from soothe.sloop.relay.store import ClarificationRow, ClarificationStore
from soothe.sloop.relay.types import RelayHandle

if TYPE_CHECKING:
    from soothe.sloop.relay.types import PolicyMode

logger = logging.getLogger(__name__)


async def capture_interrupt(
    store: ClarificationStore,
    detector: ClarificationDetector,
    *,
    interrupt_value: Any,
    interrupt_id: str,
    thread_id: str | None,
    step_id: str | None,
    step_description: str | None,
    loop_id: str,
    goal_id: str,
    loop_state: LoopStateView,
    origin_node: str,
    policy_mode: PolicyMode,
    max_pending_per_goal: int,
) -> RelayHandle | None:
    """Detect, persist, and return a handle for a captured interrupt.

    Returns `None` when the interrupt value is not a structured clarification.
    Raises `RelayQueueFullError` when the per-goal FIFO cap is exceeded.
    """
    request = detector.detect(
        interrupt_value,
        interrupt_id=interrupt_id,
        loop_state=loop_state,
        origin_node=origin_node,  # type: ignore[arg-type]
    )
    if request is None:
        return None

    pending_count = await store.count_pending_by_goal(goal_id)
    if pending_count >= max_pending_per_goal:
        raise RelayQueueFullError(goal_id, max_pending_per_goal)

    relay_id = str(uuid.uuid4())
    row = ClarificationRow.from_handle(
        relay_id=relay_id,
        loop_id=loop_id,
        goal_id=goal_id,
        handle_origin=request.origin_node,
        handle_interrupt_id=request.origin_interrupt_id,
        request=request,
        core_agent_thread_id=thread_id,
        step_id=step_id,
        step_description=step_description,
        policy_mode=policy_mode,
        captured_at=datetime.now(UTC).isoformat(),
    )
    await store.insert(row)
    logger.info(
        "[Relay] captured relay_id=%s origin=%s goal=%s queue=%d/%d",
        relay_id[:12],
        request.origin_node,
        goal_id[:12],
        pending_count + 1,
        max_pending_per_goal,
    )
    return RelayHandle(
        relay_id=relay_id,
        origin=request.origin_node,
        request=request,
        core_agent_thread_id=thread_id,
        step_id=step_id,
        step_description=step_description,
    )


__all__ = ["capture_interrupt"]
