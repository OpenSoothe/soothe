"""Job lifecycle notify intents.

Channel-agnostic payloads produced by the host NotificationRouter and
consumed by daemon NotifySink adapters (email, webhook, Feishu, …).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

NotifyKind = Literal[
    "job.completed",
    "job.failed",
    "job.suspended_timeout",
    "sla.overdue",
]


class Severity(StrEnum):
    """Severity classification for notify intents.

    Drift-aware escalation (see `router._severity_for`):
    - `info`    — normal completion, no drift signals.
    - `warning` — suspended timeout, maturity blockers, or repeated
      failures below the retry budget (the job is *drifting* away from
      a healthy outcome but is not yet terminal).
    - `error`   — terminal failure, or retry/send-back budgets
      exhausted (the job has *drifted* past recovery).
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __ge__(self, other: Severity) -> bool:
        return _SEVERITY_RANK[self] >= _SEVERITY_RANK[other]

    def __gt__(self, other: Severity) -> bool:
        return _SEVERITY_RANK[self] > _SEVERITY_RANK[other]

    def __le__(self, other: Severity) -> bool:
        return _SEVERITY_RANK[self] <= _SEVERITY_RANK[other]

    def __lt__(self, other: Severity) -> bool:
        return _SEVERITY_RANK[self] < _SEVERITY_RANK[other]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
}


class NotifyTarget(BaseModel):
    """Resolved delivery destination for one sink."""

    kind: str
    to_address: str


class NotifyIntent(BaseModel):
    """One job-root lifecycle alert to deliver across enabled sinks."""

    kind: NotifyKind
    job_id: str
    title: str
    body: str
    severity: Severity = Severity.INFO
    status: str | None = None
    description: str | None = None
    workspace: str | None = None
    error: str | None = None
    suspended_for_seconds: float | None = None
    maturity: dict[str, Any] | None = None
    progress: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Compact DAG progress: status counts + capped attention highlights "
            "(never a full goal list)"
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    generation: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def dedup_key(self) -> str:
        """Stable key for at-most-once delivery across restarts."""
        gen = self.generation or self.kind
        return f"{self.job_id}:{self.kind}:{gen}"


class DeliveryResult(BaseModel):
    """Per-sink delivery outcome (fail-soft)."""

    sink: str
    ok: bool
    detail: str = ""
    delivered_to: list[str] = Field(default_factory=list)
