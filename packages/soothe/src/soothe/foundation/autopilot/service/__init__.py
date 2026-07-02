"""Autopilot service package (RFC-222, revised 2026-05-28).

Daemon-owned autopilot orchestration. ``AutopilotService`` composes
``WorkerPool``, ``ContextProjector``, ``WorkspaceReservation``, and an
injected ``InternalEventBus``.
"""

from __future__ import annotations

from .context_projector import ContextProjector
from .context_store import (
    GoalDispatchContextStoreProtocol,
    InMemoryGoalDispatchContextStore,
)
from .durability_context_store import DurabilityGoalDispatchContextStore
from .service import AutopilotService
from .worker_pool import WorkerPool, WorkerSlot, is_autopilot_worker_loop_id
from .workspace_reservation import WorkspaceReservation

__all__ = [
    "AutopilotService",
    "ContextProjector",
    "DurabilityGoalDispatchContextStore",
    "GoalDispatchContextStoreProtocol",
    "InMemoryGoalDispatchContextStore",
    "WorkerPool",
    "WorkerSlot",
    "WorkspaceReservation",
    "is_autopilot_worker_loop_id",
]
