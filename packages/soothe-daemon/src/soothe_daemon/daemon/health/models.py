"""Data models for health check results."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    """Health check status levels."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    SKIPPED = "skipped"

    def __lt__(self, other: "CheckStatus") -> bool:
        """Compare severity levels for aggregation."""
        severity = {
            CheckStatus.OK: 0,
            CheckStatus.INFO: 1,
            CheckStatus.SKIPPED: 2,
            CheckStatus.WARNING: 3,
            CheckStatus.ERROR: 4,
        }
        return severity[self] < severity[other]

    def __le__(self, other: "CheckStatus") -> bool:
        """Compare severity levels for aggregation."""
        return self == other or self < other


@dataclass
class CheckResult:
    """Result of a single health check.

    Attributes:
        name: Unique identifier for this check (e.g., "config_file_valid")
        status: Check status (ok, warning, error, info, skipped)
        message: Human-readable result message
        details: Additional structured data (e.g., paths, values, error details)
    """

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class CategoryResult:
    """Results for a health check category.

    Attributes:
        category: Category name (e.g., "configuration", "daemon", "persistence")
        status: Aggregated status (worst of all checks)
        checks: List of individual check results
        message: Optional category-level message
    """

    category: str
    status: CheckStatus
    checks: list[CheckResult]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "category": self.category,
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
            "message": self.message,
        }


@dataclass
class HealthReport:
    """Complete health check report.

    Attributes:
        timestamp: ISO 8601 timestamp of report generation
        soothe_version: Soothe package version
        config_path: Path to config file used (or None if not loaded)
        overall_status: Aggregated status across all categories
        categories: List of category results
    """

    timestamp: str
    soothe_version: str
    config_path: str | None
    overall_status: CheckStatus
    categories: list[CategoryResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp,
            "soothe_version": self.soothe_version,
            "config_path": self.config_path,
            "overall_status": self.overall_status.value,
            "categories": [cat.to_dict() for cat in self.categories],
        }

    def get_summary(self) -> dict[str, int]:
        """Get summary counts by status.

        Returns:
            Dictionary with counts for each status level
        """
        summary = {
            "total": 0,
            "ok": 0,
            "warning": 0,
            "error": 0,
            "info": 0,
            "skipped": 0,
        }

        for category in self.categories:
            for check in category.checks:
                summary["total"] += 1
                summary[check.status.value] += 1

        return summary
