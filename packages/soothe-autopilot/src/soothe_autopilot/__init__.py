"""Autopilot — goal lifecycle orchestration and dispatch (RFC-222, RFC-625).

Autopilot manages:
- Intake (GOAL.md / user / channel guidance → CE; IG-733)
- Goal DAG orchestration (create, schedule, dependencies)
- Goal lifecycle (pending, active, completed, failed)
- Backoff reasoning on failure
- Dispatch to StrangeLoop workers

ContextEngine (`soothe.context`) is the sole source of truth for goal/step
state. AutopilotService uses ContextEngine and AutopilotMonitor for
proactive DAG management.

Public API (root exports only):
    from soothe_autopilot import AutopilotService, AutopilotMonitor

Import other types from one-level subpackages, e.g.:
    from soothe_autopilot.intake import absorb_user_guidance
    from soothe.goal_contracts import EvidenceBundle
    from soothe_autopilot.workers.pool import WorkerPool
    from soothe_autopilot.rails import LoopRailInterpreter
    from soothe_autopilot.prompts import build_consensus_prompt
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
        from soothe_autopilot.monitor import AutopilotMonitor

        return AutopilotMonitor
    if name == "AutopilotService":
        from soothe_autopilot.service import AutopilotService

        return AutopilotService

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
