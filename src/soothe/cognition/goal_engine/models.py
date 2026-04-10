"""Goal models for autonomous iteration (RFC-0007, RFC-204)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from soothe.protocols.planner import GoalReport

# RFC-204: Extended lifecycle states (7 total)
GoalStatus = Literal["pending", "active", "validated", "completed", "failed", "suspended", "blocked"]

# Terminal states that count as "resolved"
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed"})


class Goal(BaseModel):
    """A single autonomous goal.

    Args:
        id: Unique 8-char hex identifier.
        description: Human-readable goal text.
        status: Current lifecycle status (7 states per RFC-204).
        priority: Scheduling priority (0-100, higher = first).
        parent_id: Optional parent goal for hierarchical decomposition.
        depends_on: IDs of goals that must complete before this one (hard DAG edges).
        informs: IDs of goals whose findings may enrich this goal (soft dependency).
        conflicts_with: IDs of goals that must not execute concurrently (mutual exclusion).
        plan_count: Number of plans created for this goal (for P_N ID generation).
        retry_count: Number of retries attempted so far.
        max_retries: Maximum retries before permanent failure.
        send_back_count: Number of consensus send-backs used (RFC-204).
        max_send_backs: Maximum send-back rounds before suspension (RFC-204).
        report: GoalReport from execution (set on completion).
        source_file: Path to GOAL.md file that defined this goal (None if auto-created).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    status: GoalStatus = "pending"
    priority: int = 50
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    # RFC-204: Soft relationships and mutual exclusion
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    plan_count: int = 0
    retry_count: int = 0
    max_retries: int = 2
    # RFC-204: Consensus loop tracking
    send_back_count: int = 0
    max_send_backs: int = 3
    report: GoalReport | None = None
    # RFC-204: Source file for status tracking
    source_file: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
