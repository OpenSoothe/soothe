"""Main orchestration entry point with execution, branching, and analysis."""

from .agent_loop import AgentLoop
from .anchor_manager import CheckpointAnchorManager
from .context_window_manager import ContextCompactionResult, ContextWindowManager
from .executor import (
    DELEGATE_FINAL_WAVE_CAP,
    Executor,
    StepWaveQueued,
    StepWaveStart,
    compute_act_wave_finalize,
)
from .metadata_generator import generate_outcome_metadata
from .scenario_classifier import ScenarioClassification
from .synthesis import SynthesisGenerator
from .thread_switch_policy import ThreadSwitchPolicyManager

__all__ = [
    "AgentLoop",
    "CheckpointAnchorManager",
    "ContextCompactionResult",
    "ContextWindowManager",
    "DELEGATE_FINAL_WAVE_CAP",
    "Executor",
    "StepWaveQueued",
    "StepWaveStart",
    "ScenarioClassification",
    "SynthesisGenerator",
    "ThreadSwitchPolicyManager",
    "compute_act_wave_finalize",
    "generate_outcome_metadata",
]
