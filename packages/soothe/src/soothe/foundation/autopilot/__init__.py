"""Autopilot package - Layer 3 Goal lifecycle and dispatch.

Autopilot manages:
- Goal DAG orchestration (create, schedule, dependencies)
- Goal lifecycle (pending, active, completed, failed)
- Backoff reasoning on failure
- Dispatch to StrangeLoop workers

This package merges GoalEngine and AutopilotService as unified Layer 3.

Import paths:
    from soothe.foundation.autopilot import GoalEngine, AutopilotService
    from soothe.foundation.autopilot.engine.models import Goal, BackoffDecision
    from soothe.foundation.autopilot.service.worker_pool import WorkerPool
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # GoalEngine exports
    "GoalEngine",
    "Goal",
    "BackoffDecision",
    "EvidenceBundle",
    "GoalDirective",
    "GoalReport",
    # AutopilotService exports
    "AutopilotService",
    "WorkerPool",
    "WorkerSlot",
    "LoopPool",
    "LoopHandle",
    "ContextProjector",
]


def __getattr__(name: str) -> Any:
    """Lazy import autopilot modules."""
    # GoalEngine exports
    if name == "GoalEngine":
        from soothe.foundation.autopilot.engine.engine import GoalEngine

        return GoalEngine
    if name == "Goal":
        from soothe.foundation.autopilot.engine.models import Goal

        return Goal
    if name == "BackoffDecision":
        from soothe.foundation.autopilot.engine.models import BackoffDecision

        return BackoffDecision
    if name == "EvidenceBundle":
        from soothe.foundation.autopilot.engine.models import EvidenceBundle

        return EvidenceBundle
    if name == "GoalDirective":
        from soothe.protocols.planner import GoalDirective

        return GoalDirective
    if name == "GoalReport":
        from soothe.protocols.planner import GoalReport

        return GoalReport

    # AutopilotService exports
    if name == "AutopilotService":
        from soothe.foundation.autopilot.service.service import AutopilotService

        return AutopilotService
    if name == "WorkerPool":
        from soothe.foundation.autopilot.service.worker_pool import WorkerPool

        return WorkerPool
    if name == "WorkerSlot":
        from soothe.foundation.autopilot.service.worker_pool import WorkerSlot

        return WorkerSlot
    if name == "LoopPool":
        from soothe.foundation.autopilot.service.loop_pool import LoopPool

        return LoopPool
    if name == "LoopHandle":
        from soothe.foundation.autopilot.service.loop_pool import LoopHandle

        return LoopHandle
    if name == "ContextProjector":
        from soothe.foundation.autopilot.service.context_projector import ContextProjector

        return ContextProjector

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
