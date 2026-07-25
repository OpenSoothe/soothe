"""Soothe host diagnose API (called by soothed doctor)."""

from soothe.diagnose.api import (
    ALL_CATEGORIES,
    DEEP_CATEGORIES,
    VITAL_CATEGORIES,
    diagnose,
)
from soothe.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)

__all__ = [
    "ALL_CATEGORIES",
    "DEEP_CATEGORIES",
    "VITAL_CATEGORIES",
    "CategoryResult",
    "CheckResult",
    "CheckStatus",
    "aggregate_status",
    "diagnose",
]
