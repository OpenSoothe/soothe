"""Goal-related models and utilities (RFC-204, RFC-200, RFC-217, RFC-222, RFC-625).

GoalEngine deleted per RFC-625. ContextEngine (soothe.foundation.context) is now
the sole source of truth for goal/step state. This module retains shared models
used by AutopilotService, StrangeLoop workers, and ContextProjector.

Key exports:
- GoalStatus, TERMINAL_STATES, BLOCKED_STATES: Goal lifecycle states
- EvidenceBundle, BackoffDecision: Backoff reasoning models (RFC-200)
- GoalDispatchContextBundle, GoalDispatchContextContribution: IPC models (RFC-222)
- ScheduleSpec: Cron schedule math (RFC-204)
"""

from soothe.foundation.autopilot.engine.models import (
    BLOCKED_STATES,
    TERMINAL_STATES,
    BackoffDecision,
    EvidenceBundle,
    FileTouchSummary,
    Finding,
    GoalDispatchContextBundle,
    GoalDispatchContextContribution,
    GoalStatus,
    ParentFinding,
    PriorStepSummary,
    StepSummary,
    ToolCallStats,
)
from soothe.foundation.autopilot.engine.proposal_queue import Proposal, ProposalQueue
from soothe.foundation.autopilot.engine.scheduled_tasks import ScheduleSpec

__all__ = [
    "BLOCKED_STATES",
    "BackoffDecision",
    "EvidenceBundle",
    "FileTouchSummary",
    "Finding",
    "GoalDispatchContextBundle",
    "GoalDispatchContextContribution",
    "GoalStatus",
    "ParentFinding",
    "PriorStepSummary",
    "Proposal",
    "ProposalQueue",
    "ScheduleSpec",
    "StepSummary",
    "TERMINAL_STATES",
    "ToolCallStats",
]
