"""AutopilotMonitor — proactive DAG monitoring (RFC-625)."""

from __future__ import annotations

from typing import Any

from soothe.autopilot.monitor.models import (
    DagHealthReport,
    DecomposeSuggestion,
    GoalIntakeResult,
    GoalPlacement,
    MergeSuggestion,
    WireDependencySuggestion,
)

__all__ = [
    "AutopilotMonitor",
    "DagHealthReport",
    "DecomposeSuggestion",
    "GoalIntakeResult",
    "GoalPlacement",
    "MergeSuggestion",
    "WireDependencySuggestion",
]


def __getattr__(name: str) -> Any:
    """Lazy-load AutopilotMonitor to avoid import cycles with verify."""
    if name == "AutopilotMonitor":
        from soothe.autopilot.monitor.monitor import AutopilotMonitor

        return AutopilotMonitor
    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
