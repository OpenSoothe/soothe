"""Autopilot service package (RFC-222, revised 2026-05-28).

Daemon-owned autopilot orchestration. RFC-222 (revised) reframes this
package: ``AutopilotService`` will be constructed once per daemon and
compose ``GoalEngine``, ``WorkerPool``, ``ContextProjector``,
``WorkspaceReservation``, and an injected ``InternalEventBus``. Phase A
(IG-442) ships the new component modules without wiring them up; later
phases swap the daemon's construction over.

Architecture:
- service.py: AutopilotService (today: per-runner; later: daemon-owned)
- loop_pool.py: legacy LoopPool / LoopHandle (Phase A keeps for backcompat)
- worker_pool.py: WorkerPool over LoopRunnerFactory (RFC-222 revised)
- context_projector.py: ContextProjector (parents → bundle)
- context_store.py: GoalDispatchContextStore (per-goal contributions)
- workspace_reservation.py: WorkspaceReservation (scheduling-time gate)
"""

from __future__ import annotations

from .context_projector import ContextProjector
from .context_store import (
    GoalDispatchContextStoreProtocol,
    InMemoryGoalDispatchContextStore,
)
from .loop_pool import LoopHandle, LoopPool
from .service import AutopilotService
from .worker_pool import WorkerPool, WorkerSlot, is_autopilot_worker_loop_id
from .workspace_reservation import WorkspaceReservation

__all__ = [
    "AutopilotService",
    "ContextProjector",
    "GoalDispatchContextStoreProtocol",
    "InMemoryGoalDispatchContextStore",
    "LoopHandle",
    "LoopPool",
    "WorkerPool",
    "WorkerSlot",
    "WorkspaceReservation",
    "is_autopilot_worker_loop_id",
]
