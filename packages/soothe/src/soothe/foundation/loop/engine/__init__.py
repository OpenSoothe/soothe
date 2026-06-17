"""Main orchestration entry point with execution, branching, and analysis."""

from .act_wave_finalize import DELEGATE_FINAL_WAVE_CAP, compute_act_wave_finalize
from .anchor_manager import CheckpointAnchorManager
from .context_window_manager import ContextCompactionResult, ContextWindowManager
from .executor import Executor, ephemeral_execute_stream_enabled
from .metadata_generator import generate_outcome_metadata
from .scenario_classifier import ScenarioClassification
from .step_wave_types import StepWaveQueued, StepWaveStart
from .strange_loop import StrangeLoop
from .synthesis import SynthesisGenerator, generate_user_fallback_summary
from .thread_switch_policy import ThreadSwitchPolicyManager

__all__ = [
    "CheckpointAnchorManager",
    "compute_act_wave_finalize",
    "ContextCompactionResult",
    "ContextWindowManager",
    "DELEGATE_FINAL_WAVE_CAP",
    "ephemeral_execute_stream_enabled",
    "Executor",
    "generate_outcome_metadata",
    "generate_user_fallback_summary",
    "ScenarioClassification",
    "StrangeLoop",
    "StepWaveQueued",
    "StepWaveStart",
    "SynthesisGenerator",
    "ThreadSwitchPolicyManager",
]
