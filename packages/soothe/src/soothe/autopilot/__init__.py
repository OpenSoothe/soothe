"""Autopilot package - Layer 3 Goal lifecycle and dispatch (RFC-222, RFC-625).

Autopilot manages:
- Goal DAG orchestration (create, schedule, dependencies)
- Goal lifecycle (pending, active, completed, failed)
- Backoff reasoning on failure
- Dispatch to StrangeLoop workers

RFC-625: ContextEngine (soothe.context) is the sole source of truth
for goal/step state. AutopilotService uses ContextEngine and AutopilotMonitor
for proactive DAG management.

Import paths:
    from soothe.autopilot.service import AutopilotService, AutopilotMonitor
    from soothe.autopilot.engine_models import BackoffDecision, EvidenceBundle
    from soothe.context.models import GoalNode
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AutopilotMonitor",
    "BackoffDecision",
    "EvidenceBundle",
    "GoalDirective",
    "GoalReport",
    "AutopilotService",
    "WorkerPool",
    "WorkerSlot",
    "ContextProjector",
]


def __getattr__(name: str) -> Any:
    """Lazy import autopilot modules."""
    if name == "AutopilotMonitor":
        from soothe.autopilot.monitor import AutopilotMonitor

        return AutopilotMonitor
    if name == "BackoffDecision":
        from soothe.autopilot.engine_models import BackoffDecision

        return BackoffDecision
    if name == "EvidenceBundle":
        from soothe.autopilot.engine_models import EvidenceBundle

        return EvidenceBundle
    if name == "GoalDirective":
        from soothe_sdk.protocols.planner import GoalDirective

        return GoalDirective
    if name == "GoalReport":
        from soothe_sdk.protocols.planner import GoalReport

        return GoalReport
    if name == "AutopilotService":
        from soothe.autopilot.service import AutopilotService

        return AutopilotService
    if name == "WorkerPool":
        from soothe.autopilot.worker_pool import WorkerPool

        return WorkerPool
    if name == "WorkerSlot":
        from soothe.autopilot.worker_pool import WorkerSlot

        return WorkerSlot
    if name == "ContextProjector":
        from soothe.autopilot.context_projector import ContextProjector

        return ContextProjector

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
