"""Reconcile: three-way consistency check (relay store, CE, CoreAgent).

Called before `build_resume_directive()` and on worker startup. Any
inconsistency causes fail-closed behavior — the goal is marked `failed`
and re-dispatched. No silent recovery.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from soothe.sloop.relay.store import ClarificationStore
from soothe.sloop.relay.types import ReconcileReport

logger = logging.getLogger(__name__)


class _CEProtocol(Protocol):
    def get_goal(self, goal_id: str) -> Any: ...


async def reconcile_clarification(
    store: ClarificationStore,
    *,
    relay_id: str,
    ce: Any | None = None,
    checkpointer: Any | None = None,
) -> ReconcileReport:
    """Three-way consistency check before resume."""
    row = await store.get(relay_id)
    if row is None:
        return ReconcileReport(
            consistent=False,
            conflict=f"relay row not found (relay_id={relay_id[:12]})",
        )

    relay_status = row.status  # type: ignore[assignment]
    if relay_status not in ("answered", "consumed"):
        return ReconcileReport(
            consistent=False,
            relay_status=relay_status,  # type: ignore[arg-type]
            conflict=f"relay status is {relay_status!r}, expected 'answered' or 'consumed'",
        )

    ce_goal_status: str | None = None
    if ce is not None:
        try:
            goal = ce.get_goal(row.goal_id)
            if goal is not None:
                ce_goal_status = getattr(goal, "status", None)
        except Exception:
            logger.warning("[Relay] CE get_goal failed (relay=%s)", relay_id[:12], exc_info=True)

    if ce_goal_status == "awaiting_clarification":
        return ReconcileReport(
            consistent=False,
            relay_status=relay_status,  # type: ignore[arg-type]
            ce_goal_status=ce_goal_status,
            conflict="CE goal still 'awaiting_clarification' — not unblocked",
        )

    core_agent_thread_ok: bool | None = None
    if row.core_agent_thread_id and checkpointer is not None:
        try:
            from soothe.sloop.orchestrator.checkpoint import (
                snapshot_has_resumable_interrupt,
            )

            config = {"configurable": {"thread_id": row.core_agent_thread_id}}
            snapshot = await checkpointer.aget_state(config)
            core_agent_thread_ok = snapshot_has_resumable_interrupt(snapshot)
        except Exception:
            logger.warning(
                "[Relay] thread liveness check failed (relay=%s)", relay_id[:12], exc_info=True
            )
            core_agent_thread_ok = False

        if core_agent_thread_ok is False:
            return ReconcileReport(
                consistent=False,
                relay_status=relay_status,  # type: ignore[arg-type]
                ce_goal_status=ce_goal_status,
                core_agent_thread_ok=False,
                conflict=(
                    f"CoreAgent thread {row.core_agent_thread_id[:12]} "
                    "no longer has a resumable interrupt"
                ),
            )

    logger.info(
        "[Relay] reconcile OK relay_id=%s relay=%s ce=%s thread_ok=%s",
        relay_id[:12],
        relay_status,
        ce_goal_status,
        core_agent_thread_ok,
    )
    return ReconcileReport(
        consistent=True,
        relay_status=relay_status,  # type: ignore[arg-type]
        ce_goal_status=ce_goal_status,
        core_agent_thread_ok=core_agent_thread_ok,
    )


__all__ = ["reconcile_clarification"]
