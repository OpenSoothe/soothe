"""Host LangGraph configurable keys for CoreAgent orchestration hooks."""

from __future__ import annotations

# Set True during goal-completion synthesis so CoreAgent runs read-only.
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"

# Set True on StrangeLoop step THREADS when agent.loop.decompose.enabled.
SOOTHE_DECOMPOSE_ENABLED_KEY = "soothe_decompose_enabled"

# Step id owning the current THREAD; mirrors the decompose runtime contextvar.
SOOTHE_DECOMPOSE_STEP_ID_KEY = "soothe_decompose_step_id"

__all__ = [
    "SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY",
    "SOOTHE_DECOMPOSE_ENABLED_KEY",
    "SOOTHE_DECOMPOSE_STEP_ID_KEY",
]
