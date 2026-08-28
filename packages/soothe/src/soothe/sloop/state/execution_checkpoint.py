"""GoalIndexEntry for checkpoint goal index."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class GoalIndexEntry(BaseModel):
    """Minimal goal index entry for checkpoint.

       Goal state recovered from CE GoalNode. Checkpoint only stores
       goal_id and status for loop-level tracking.

    §4: GoalIndexEntry stores loop-level goal index metadata only.
       CE GoalNode is the authoritative source for goal state.

       Attributes:
           goal_id: Goal identifier (CE lookup key, 8-char hex).
           status: Goal execution status.
           thread_id: Thread that executed this goal.
           started_at: Goal start timestamp.
           completed_at: Goal completion timestamp (None if running).
           duration_ms: Goal execution duration in milliseconds.
           tokens_used: Tokens used for this goal.
    """

    # Identity (CE lookup key)
    goal_id: str = Field(description="Goal identifier (CE lookup key)")

    # Status (for loop-level tracking, CE GoalNode has full status)
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"] = Field(
        default="running", description="Goal execution status"
    )

    # Thread assignment (for metrics, not goal content)
    thread_id: str = Field(description="Thread that executed this goal")

    # Timestamps (for metrics only)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Goal start timestamp"
    )
    completed_at: datetime | None = Field(
        default=None, description="Goal completion timestamp (None if running)"
    )

    # Metrics (execution-level, not goal content)
    duration_ms: int = Field(default=0, ge=0, description="Goal execution duration in milliseconds")
    tokens_used: int = Field(default=0, ge=0, description="Tokens used for this goal")
