"""Foundation package - three-layer architecture + shared utilities.

This package contains:
- foundation.core: Layer 1 CoreAgent runtime
- foundation.loop: Layer 2 AgentLoop orchestration
- foundation.autopilot: Layer 3 Goal lifecycle and dispatch
- foundation.events: Shared event system
- foundation.workspace: Shared workspace resolution
- foundation.persistence: Shared artifact store

Import paths:
    from soothe.foundation.core import CoreAgent, create_soothe_agent
    from soothe.foundation.loop import AgentLoop, LoopState
    from soothe.foundation.autopilot import GoalEngine, AutopilotService
    from soothe.foundation.events import GOAL_CREATED
    from soothe.foundation.workspace import resolve_daemon_workspace
"""

from __future__ import annotations

# Re-export from base utilities
from soothe.foundation.ai_message import extract_text_from_ai_message
from soothe.foundation.autopilot import AutopilotService, GoalEngine

# Re-export from subpackages for convenience
from soothe.foundation.core import CoreAgent, create_soothe_agent

# Re-export from shared utilities
from soothe.foundation.events import (
    GOAL_COMPLETED,
    GOAL_CREATED,
    GOAL_FAILED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
)
from soothe.foundation.loop import AgentLoop, LoopState, PlanResult
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
    "AgentLoop",
    "LoopState",
    "PlanResult",
    # Layer 3: Autopilot
    "GoalEngine",
    "AutopilotService",
    # Events
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
