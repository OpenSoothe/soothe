"""Context Engine — unified context management for goals, steps, and projection (RFC-624, RFC-625).

Located in soothe.context as foundational infrastructure.
"""

from soothe.context.engine import ContextEngine
from soothe.context.ledger import LedgerManager
from soothe.context.models import (
    BLOCKED_STATES,
    TERMINAL_STATES,
    EpisodeSummary,
    EvidenceEntry,
    GoalNode,
    GoalStatus,
    GoalStepDAG,
    GoalStepDAGSnapshot,
    StepDAG,
    StepExecution,
    StepNode,
    StepStatus,
)
from soothe.context.planning_goal_planner import GoalPlanningSubengine
from soothe.context.planning_scheduling import GoalScheduler, PlanningFacade
from soothe.context.planning_step_planner import StepPlanManagerAdapter, StepPlanningSubengine
from soothe.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.context.semantic import SemanticLoader

__all__ = [
    "ContextEngine",
    "ContextBundle",
    "ProjectionConfig",
    "ProjectionEngine",
    "EpisodeSummary",
    "EvidenceEntry",
    "GoalNode",
    "StepNode",
    "StepExecution",
    "StepDAG",
    "GoalStepDAG",
    "GoalStepDAGSnapshot",
    "GoalStatus",
    "StepStatus",
    "TERMINAL_STATES",
    "BLOCKED_STATES",
    "LedgerManager",
    "SemanticLoader",
    "GoalPlanningSubengine",
    "GoalScheduler",
    "PlanningFacade",
    "StepPlanManagerAdapter",
    "StepPlanningSubengine",
]
