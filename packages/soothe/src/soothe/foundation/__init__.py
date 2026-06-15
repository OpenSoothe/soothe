"""Foundation package - three-layer architecture + shared utilities.

This package contains:
- foundation.core: Layer 1 CoreAgent runtime
- foundation.loop: Layer 2 StrangeLoop orchestration
- foundation.autopilot: Layer 3 Goal lifecycle and dispatch (RFC-625)
- foundation.context: Unified goal/step state management (RFC-625)
- foundation.events: Shared event system
- foundation.workspace: Shared workspace resolution
- foundation.persistence: Shared artifact store

RFC-625: GoalEngine deleted. ContextEngine is the sole source of truth.
Import paths:
    from soothe.foundation.core import CoreAgent, create_soothe_agent
    from soothe.foundation.loop import StrangeLoop, LoopState
    from soothe.foundation.autopilot import AutopilotService, AutopilotMonitor
    from soothe.foundation.context import ContextEngine, GoalNode
    from soothe.foundation.events import GOAL_CREATED
    from soothe.foundation.workspace import resolve_daemon_workspace
"""

from __future__ import annotations

from typing import Any

# Re-export from base utilities (no circular deps)
from soothe.foundation.ai_message import extract_text_from_ai_message

# Re-export from subpackages for convenience (no circular deps)
from soothe.foundation.core import CoreAgent, create_soothe_agent

# Re-export from shared utilities (no circular deps)
from soothe.foundation.loop import LoopState, PlanResult, StrangeLoop
from soothe.foundation.workspace import (
    FrameworkFilesystem,
    resolve_daemon_workspace,
    resolve_workspace_for_stream,
    validate_client_workspace,
)

__all__ = [
    # Layer 1: Core
    "CoreAgent",
    "create_soothe_agent",
    # Layer 2: Loop
    "StrangeLoop",
    "LoopState",
    "PlanResult",
    # Layer 3: Autopilot (RFC-625) - lazy loaded
    "AutopilotService",
    "AutopilotMonitor",
    # Events - lazy loaded
    "GOAL_CREATED",
    "GOAL_COMPLETED",
    "GOAL_FAILED",
    "ITERATION_STARTED",
    "ITERATION_COMPLETED",
    # Workspace
    "resolve_daemon_workspace",
    "resolve_workspace_for_stream",
    "validate_client_workspace",
    "FrameworkFilesystem",
    # Utilities
    "extract_text_from_ai_message",
]


def __getattr__(name: str) -> Any:
    """Lazy import for modules with potential circular deps."""
    if name == "AutopilotService":
        from soothe.foundation.autopilot.service.service import AutopilotService

        return AutopilotService
    if name == "AutopilotMonitor":
        from soothe.foundation.autopilot.monitor.monitor import AutopilotMonitor

        return AutopilotMonitor
    if name in (
        "GOAL_CREATED",
        "GOAL_COMPLETED",
        "GOAL_FAILED",
        "ITERATION_STARTED",
        "ITERATION_COMPLETED",
    ):
        from soothe.foundation.events import (
            GOAL_COMPLETED,
            GOAL_CREATED,
            GOAL_FAILED,
            ITERATION_COMPLETED,
            ITERATION_STARTED,
        )

        return {
            "GOAL_CREATED": GOAL_CREATED,
            "GOAL_COMPLETED": GOAL_COMPLETED,
            "GOAL_FAILED": GOAL_FAILED,
            "ITERATION_STARTED": ITERATION_STARTED,
            "ITERATION_COMPLETED": ITERATION_COMPLETED,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
