"""Context Engine planning submodule (RFC-624 Phase 3c).

Provides step-level planning, goal-level planning, and scheduling
as composable subengines within ContextEngine.

Usage:
    ce = ContextEngine()
    ce.planning.step      # StepPlanningSubengine
    ce.planning.goal      # GoalPlanningSubengine
    ce.planning.scheduler # GoalScheduler
"""

from __future__ import annotations

from dataclasses import dataclass

from .goal_planner import GoalPlanningSubengine
from .scheduling import GoalScheduler
from .step_planner import StepPlanManagerAdapter, StepPlanningSubengine

__all__ = [
    "GoalPlanningSubengine",
    "GoalScheduler",
    "PlanningFacade",
    "StepPlanManagerAdapter",
    "StepPlanningSubengine",
]


@dataclass
class PlanningFacade:
    """Unified access point for ContextEngine's planning capabilities."""

    step: StepPlanningSubengine
    goal: GoalPlanningSubengine
    scheduler: GoalScheduler
