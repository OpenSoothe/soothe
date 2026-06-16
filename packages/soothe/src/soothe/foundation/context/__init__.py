"""Context Engine — unified context management for goals, steps, and projection (RFC-624, RFC-625).

Located in soothe.foundation.context as foundational infrastructure.
"""

from soothe.foundation.context.engine import ContextEngine, EngineEvent
from soothe.foundation.context.ledger import LedgerManager
from soothe.foundation.context.models import (
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
from soothe.foundation.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.foundation.context.semantic import SemanticLoader

__all__ = [
    "ContextEngine",
    "EngineEvent",
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
]
