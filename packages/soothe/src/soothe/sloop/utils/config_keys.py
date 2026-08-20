"""Host LangGraph configurable keys for CoreAgent orchestration hooks."""

from __future__ import annotations

# Set True during goal-completion synthesis so CoreAgent runs read-only.
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"

# Step id owning the current StrangeLoop step THREAD; mirrors the decompose
# runtime contextvar. When set, DecomposeTaskMiddleware injects decompose_task.
SOOTHE_DECOMPOSE_STEP_ID_KEY = "soothe_decompose_step_id"

# Eval step id owning the current readonly coverage-audit thread.
SOOTHE_EVAL_STEP_ID_KEY = "soothe_eval_step_id"

__all__ = [
    "SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY",
    "SOOTHE_DECOMPOSE_STEP_ID_KEY",
    "SOOTHE_EVAL_STEP_ID_KEY",
]
