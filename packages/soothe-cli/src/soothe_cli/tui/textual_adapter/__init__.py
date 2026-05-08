"""Public API for the textual_adapter sub-package."""

from soothe_cli.tui.textual_adapter._adapter import (
    AGENT_LOOP_GOAL_COMPLETED,
    AGENT_LOOP_GOAL_STARTED,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
    ModelStats,
    SessionStats,
    SpinnerStatus,
    TextualUIAdapter,
    format_token_count,
)
from soothe_cli.tui.textual_adapter._stream_formatting import print_usage_table
from soothe_cli.tui.textual_adapter._turn import execute_task_textual

__all__ = [
    "TextualUIAdapter",
    "execute_task_textual",
    "print_usage_table",
    "ModelStats",
    "SessionStats",
    "SpinnerStatus",
    "format_token_count",
    "AGENT_LOOP_GOAL_COMPLETED",
    "AGENT_LOOP_GOAL_STARTED",
    "AGENT_LOOP_STEP_COMPLETED",
    "AGENT_LOOP_STEP_STARTED",
]
