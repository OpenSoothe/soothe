"""Cron Service models (RFC-229).

Dataclasses and enums for scheduled job representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ScheduleKind(StrEnum):
    """Schedule kind extracted from natural language.

    Values:
        ONCE: One-shot at specific datetime (no recurrence)
        DELAY: Relative delay from now (e.g., "in 2 hours")
        AT: Specific datetime (e.g., "tomorrow at 9am")
        EVERY: Recurring interval (e.g., "every hour", "daily")
        CRON: Cron expression (e.g., "0 9 * * 1-5")
    """

    ONCE = "once"
    DELAY = "delay"
    AT = "at"
    EVERY = "every"
    CRON = "cron"


class JobStatus(StrEnum):
    """Status of a scheduled job.

    Values:
        PENDING: Waiting for scheduled time
        RUNNING: Currently executing
        COMPLETED: Finished successfully (one-shot) or expired (recurring)
        FAILED: Execution failed
        CANCELLED: User cancelled
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExtractionResult:
    """Result of LLM-based schedule extraction.

    Attributes:
        description: Extracted task description in imperative form.
        schedule_kind: Kind of schedule (once, delay, at, every, cron).
        schedule_value: Parsed schedule value (duration, datetime, or cron expr).
        end_condition: Optional end condition (e.g., "until 2026-06-30", "for 2 weeks").
        confidence: Extraction confidence score (0.0-1.0).
        raw_input: Original natural language input (for debugging).
    """

    description: str
    schedule_kind: ScheduleKind
    schedule_value: str
    end_condition: str | None = None
    confidence: float = 0.0
    raw_input: str = ""

    def is_valid(self, threshold: float = 0.5) -> bool:
        """Check if extraction confidence meets threshold.

        Args:
            threshold: Minimum confidence required (default 0.5).

        Returns:
            True if confidence >= threshold.
        """
        return self.confidence >= threshold

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "description": self.description,
            "schedule_kind": self.schedule_kind.value,
            "schedule_value": self.schedule_value,
            "end_condition": self.end_condition,
            "confidence": self.confidence,
            "raw_input": self.raw_input,
        }


@dataclass
class CronJob:
    """A scheduled job for the cron service.

    Attributes:
        id: Unique job identifier (UUID hex).
        user_id: Owner user identifier.
        description: Task description in imperative form.
        schedule_kind: Kind of schedule.
        schedule_value: Parsed schedule value.
        end_condition: Optional end condition for recurring jobs.
        priority: Goal priority (1-100, default 50).
        status: Current job status.
        next_run: Computed next execution time.
        last_run: Last execution time (null if never run).
        run_count: Number of times this job has been executed.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: str
    user_id: str
    description: str
    schedule_kind: ScheduleKind
    schedule_value: str
    end_condition: str | None = None
    priority: int = 50
    status: JobStatus = JobStatus.PENDING
    next_run: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    last_run: datetime | None = None
    run_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def is_recurring(self) -> bool:
        """Check if this job is recurring.

        Returns:
            True if schedule kind is EVERY or CRON.
        """
        return self.schedule_kind in (ScheduleKind.EVERY, ScheduleKind.CRON)

    def is_one_shot(self) -> bool:
        """Check if this job is one-shot (non-recurring).

        Returns:
            True if schedule kind is ONCE, DELAY, or AT.
        """
        return self.schedule_kind in (ScheduleKind.ONCE, ScheduleKind.DELAY, ScheduleKind.AT)

    def is_due(self, now: datetime | None = None) -> bool:
        """Check if this job is due for execution.

        Args:
            now: Reference time. Defaults to current time.

        Returns:
            True if status is PENDING and next_run <= now.
        """
        now = now or datetime.now(tz=UTC)
        return self.status == JobStatus.PENDING and self.next_run <= now

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for DB storage.
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "description": self.description,
            "schedule_kind": self.schedule_kind.value,
            "schedule_value": self.schedule_value,
            "end_condition": self.end_condition,
            "priority": self.priority,
            "status": self.status.value,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        """Create CronJob from dictionary.

        Args:
            data: Dictionary with job fields.

        Returns:
            CronJob instance.
        """
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            description=data["description"],
            schedule_kind=ScheduleKind(data["schedule_kind"]),
            schedule_value=data["schedule_value"],
            end_condition=data.get("end_condition"),
            priority=data.get("priority", 50),
            status=JobStatus(data.get("status", "pending")),
            next_run=datetime.fromisoformat(data["next_run"])
            if data.get("next_run")
            else datetime.now(tz=UTC),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            run_count=data.get("run_count", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(tz=UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(tz=UTC),
        )
