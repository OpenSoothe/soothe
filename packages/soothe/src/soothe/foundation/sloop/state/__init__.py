"""State management and persistence."""

from .checkpoint import (
    GoalExecutionRecord,
    StrangeLoopCheckpoint,
    WorkingMemoryState,
)
from .execution_checkpoint import (
    ExecutionCheckpoint,
    GoalIndexEntry,
    WaveMetrics,
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
    "ExecutionCheckpoint",
    "GoalExecutionRecord",
    "GoalIndexEntry",
    "LoopState",
    "LoopWorkingMemory",
    "PlanResult",
    "StrangeLoopCheckpoint",
    "StrangeLoopStateManager",
    "StepAction",
    "StepResult",
    "WaveMetrics",
    "WorkingMemoryState",
]
