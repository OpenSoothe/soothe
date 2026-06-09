"""State management and persistence."""

from .checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    WorkingMemoryState,
)
from .manager import AgentLoopStateManager
from .schemas import (
    AgentDecision,
    EvidenceEntry,
    LoopState,
    PlanResult,
    StepAction,
    StepResult,
)
from .working_memory import LoopWorkingMemory

# RFC-225 / IG-445: resolve the forward refs in GoalExecutionRecord after
# schemas finished loading.
GoalExecutionRecord.model_rebuild(
    _types_namespace={
        "PlanResult": PlanResult,
        "StepResult": StepResult,
        "EvidenceEntry": EvidenceEntry,
    }
)

__all__ = [
    "AgentDecision",
    "AgentLoopCheckpoint",
    "AgentLoopStateManager",
    "EvidenceEntry",
    "GoalExecutionRecord",
    "LoopState",
    "LoopWorkingMemory",
    "PlanResult",
    "StepAction",
    "StepResult",
    "WorkingMemoryState",
]
