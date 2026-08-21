"""Host LangGraph configurable keys for CoreAgent orchestration hooks."""

from __future__ import annotations

from typing import Any

# Set True during goal-completion synthesis so CoreAgent runs read-only.
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"

# Step id owning the current StrangeLoop step THREAD; mirrors the decompose
# runtime contextvar. When set, DecomposeTaskMiddleware injects decompose_task.
SOOTHE_DECOMPOSE_STEP_ID_KEY = "soothe_decompose_step_id"

# Eval step id owning the current readonly coverage-audit thread.
SOOTHE_EVAL_STEP_ID_KEY = "soothe_eval_step_id"

# Interaction mode propagated to CoreAgent step threads ("agent" | "ask" | "plan").
SOOTHE_INTERACTION_MODE_KEY = "soothe_interaction_mode"


def positive_config_int(value: Any, default: int, *, minimum: int = 1) -> int:
    """Coerce a config budget to an int at or above ``minimum``.

    MagicMock and other non-ints must not collapse to ``1`` via ``int()``.
    """
    if type(value) is int and value >= minimum:
        return value
    return default


__all__ = [
    "SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY",
    "SOOTHE_DECOMPOSE_STEP_ID_KEY",
    "SOOTHE_EVAL_STEP_ID_KEY",
    "SOOTHE_INTERACTION_MODE_KEY",
    "positive_config_int",
]
