"""Autopilot — goal lifecycle orchestration and dispatch (RFC-222, RFC-625).

Autopilot manages:
- Cognition intake (GOAL.md / user / channel guidance → CE; IG-733)
- Goal DAG orchestration (create, schedule, dependencies)
- Goal lifecycle (pending, active, completed, failed)
- Backoff reasoning on failure
- Dispatch to StrangeLoop workers

ContextEngine (`soothe.context`) is the sole source of truth for goal/step
state. AutopilotService uses ContextEngine and AutopilotMonitor for
proactive DAG management.

Public API (root exports only):
    from soothe.autopilot import AutopilotService, AutopilotMonitor

Import other types from one-level subpackages, e.g.:
    from soothe.autopilot.cognition import absorb_user_guidance
    from soothe.autopilot.dispatch.models import EvidenceBundle
    from soothe.autopilot.workers.pool import WorkerPool
    from soothe.autopilot.rail import LoopRailInterpreter
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AutopilotMonitor",
    "AutopilotService",
]


def __getattr__(name: str) -> Any:
    """Lazy import root public symbols."""
    if name == "AutopilotMonitor":
        from soothe.autopilot.monitor import AutopilotMonitor

        return AutopilotMonitor
    if name == "AutopilotService":
        from soothe.autopilot.service import AutopilotService

        return AutopilotService

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
