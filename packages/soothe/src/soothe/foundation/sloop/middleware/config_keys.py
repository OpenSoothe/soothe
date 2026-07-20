"""Host LangGraph configurable keys for CoreAgent orchestration hooks."""

from __future__ import annotations

# Set True during goal-completion synthesis so CoreAgent runs read-only.
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"

# Catalog subagent name for execute-step task-only enforcement.
SOOTHE_STEP_SUBAGENT_CONFIG_KEY = "soothe_step_subagent"

__all__ = [
    "SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY",
    "SOOTHE_STEP_SUBAGENT_CONFIG_KEY",
]
