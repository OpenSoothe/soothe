"""State management and persistence."""

from .checkpoint import (
    GoalExecutionRecord,
    StrangeLoopCheckpoint,
    WorkingMemoryState,
)
from .schemas import (
    AgentDecision,
    EvidenceEntry,
    LoopState,
    PlanResult,
    StepAction,
    StepResult,
)
from .sloop_manager import StrangeLoopStateManager
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
    "EvidenceEntry",
    "GoalExecutionRecord",
    "LoopState",
    "LoopWorkingMemory",
    "PlanResult",
    "StrangeLoopCheckpoint",
    "StrangeLoopStateManager",
    "StepAction",
    "StepResult",
    "WorkingMemoryState",
]
