"""Goal lifecycle management and related utilities (RFC-0007, RFC-204, RFC-200, RFC-217, RFC-222)."""

from soothe.foundation.autopilot.engine.backoff_reasoner import GoalBackoffReasoner
from soothe.foundation.autopilot.engine.engine import GoalEngine
from soothe.foundation.autopilot.engine.file_lock_registry import (
    FileConflictError,
    FileLockEntry,
    FileLockRegistry,
)
from soothe.foundation.autopilot.engine.models import (
    FileTouchSummary,
    Finding,
    Goal,
    GoalDispatchContextBundle,
    GoalDispatchContextContribution,
    GoalStatus,
    ParentFinding,
    PriorStepSummary,
    StepSummary,
    ToolCallStats,
)
from soothe.foundation.autopilot.engine.proposal_queue import Proposal, ProposalQueue
from soothe.foundation.autopilot.engine.scheduled_tasks import (
    ScheduledTask,
    SchedulerService,
    ScheduleSpec,
)

__all__ = [
    "FileConflictError",
    "FileLockEntry",
    "FileLockRegistry",
    "FileTouchSummary",
    "Finding",
    "Goal",
    "GoalBackoffReasoner",
    "GoalDispatchContextBundle",
    "GoalDispatchContextContribution",
    "GoalEngine",
    "GoalStatus",
    "ParentFinding",
    "PriorStepSummary",
    "Proposal",
    "ProposalQueue",
    "ScheduleSpec",
    "ScheduledTask",
    "SchedulerService",
    "StepSummary",
    "ToolCallStats",
]
