"""Core entities module (RFC-228, RFC-626).

This module provides core entity abstractions for job management:
- Job: Facade over root GoalNode
- JobState: Job lifecycle state enum
- JobCheckpoint: IPC checkpoint value object
"""

from soothe.foundation.core.entities.job import (
    JOB_BLOCKED_STATES,
    JOB_TERMINAL_STATES,
    Job,
    JobCheckpoint,
    JobState,
)

__all__ = [
    "Job",
    "JobState",
    "JobCheckpoint",
    "JOB_TERMINAL_STATES",
    "JOB_BLOCKED_STATES",
]
