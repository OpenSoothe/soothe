"""Job lifecycle notify intents (IG-713).

Channel-agnostic payloads produced by the host NotificationRouter and
consumed by daemon NotifySink adapters (email, webhook, Feishu, …).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NotifyKind = Literal["job.completed", "job.failed", "job.suspended_timeout"]
NotifySeverity = Literal["info", "warning", "error"]

KIND_TO_EVENT_FLAG: dict[str, str] = {
    "job.completed": "job_completed",
    "job.failed": "job_failed",
    "job.suspended_timeout": "job_suspended_timeout",
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
    severity: NotifySeverity = "info"
    status: str | None = None
    description: str | None = None
    workspace: str | None = None
    error: str | None = None
    suspended_for_seconds: float | None = None
    maturity: dict[str, Any] | None = None
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
