"""Main orchestration entry point with execution, branching, and analysis."""

from .act_wave_finalize import DELEGATE_FINAL_WAVE_CAP, compute_act_wave_finalize
from .anchor_manager import CheckpointAnchorManager
from .context_window_manager import ContextCompactionResult, ContextWindowManager
from .executor import Executor
from .metadata_generator import generate_outcome_metadata
from .scenario_classifier import ScenarioClassification
from .step_wave_types import StepWaveQueued, StepWaveStart
from .synthesis import SynthesisGenerator, generate_user_fallback_summary
from .thread_switch_policy import ThreadSwitchPolicyManager

_LAZY_EXPORTS = {
    "StrangeLoop": (".strange_loop", "StrangeLoop"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr = _LAZY_EXPORTS[name]
        import importlib

        module = importlib.import_module(module_name, __name__)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CheckpointAnchorManager",
    "compute_act_wave_finalize",
    "ContextCompactionResult",
    "ContextWindowManager",
    "DELEGATE_FINAL_WAVE_CAP",
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
