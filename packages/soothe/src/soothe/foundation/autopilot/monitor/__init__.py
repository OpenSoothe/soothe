"""AutopilotMonitor - proactive DAG monitoring submodule (RFC-625).

AutopilotMonitor handles:
- LLM-driven goal DAG verification (health, placement, post-completion)
- Goal intake with placement analysis
- Backoff reasoning on goal failure
- Multi-mode dreaming (episodic, procedure, semantic, profile)
"""

from soothe.foundation.autopilot.monitor.backoff_reasoner import GoalBackoffReasoner
from soothe.foundation.autopilot.monitor.dreaming_coordinator import DreamingCoordinator
from soothe.foundation.autopilot.monitor.goal_dag_verifier import GoalDAGVerifier
from soothe.foundation.autopilot.monitor.goal_intake_handler import GoalIntakeHandler
from soothe.foundation.autopilot.monitor.models import (
    DagHealthReport,
    DecomposeSuggestion,
    DreamingContext,
    DreamingMode,
    DreamingScope,
    GoalIntakeResult,
    GoalPlacement,
    MergeSuggestion,
    ModeSwitchResult,
)
from soothe.foundation.autopilot.monitor.monitor import AutopilotMonitor

__all__ = [
    "AutopilotMonitor",
    "DreamingCoordinator",
    "GoalBackoffReasoner",
    "GoalDAGVerifier",
    "GoalIntakeHandler",
    "DagHealthReport",
    "DecomposeSuggestion",
    "DreamingContext",
    "DreamingMode",
    "DreamingScope",
    "GoalIntakeResult",
    "GoalPlacement",
    "MergeSuggestion",
    "ModeSwitchResult",
]
