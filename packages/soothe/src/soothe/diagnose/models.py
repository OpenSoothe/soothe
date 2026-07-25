"""Lightweight diagnose result models (dict-contract compatible)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import total_ordering
from typing import Any


@total_ordering
class CheckStatus(StrEnum):
    """Diagnose check status levels."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    SKIPPED = "skipped"

    @property
    def severity(self) -> int:
        """Numeric severity for aggregation (higher = worse)."""
        return {
            CheckStatus.OK: 0,
            CheckStatus.INFO: 1,
            CheckStatus.SKIPPED: 2,
            CheckStatus.WARNING: 3,
            CheckStatus.ERROR: 4,
        }[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, CheckStatus):
            return self.severity < other.severity
        return NotImplemented


@dataclass
class CheckResult:
    """Result of a single diagnose check."""

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the shared diagnose dict contract."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class CategoryResult:
    """Results for one diagnose category."""

    category: str
    status: CheckStatus
    checks: list[CheckResult]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the shared diagnose dict contract."""
        return {
            "category": self.category,
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
            "message": self.message,
        }


def aggregate_status(statuses: list[CheckStatus]) -> CheckStatus:
    """Aggregate multiple statuses into one (worst wins)."""
    if not statuses:
        return CheckStatus.OK
    return max(statuses, key=lambda s: s.severity)
