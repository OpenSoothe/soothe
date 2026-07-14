"""Runtime patches for coding CoreAgent implementation."""

from soothe.foundation.coreagent.coding.patches.execute_filter import (
    apply_execute_tool_removal_patch,
    without_deepagents_execute_tool,
)
from soothe.foundation.coreagent.coding.patches.summarization import apply_summarization_patches
from soothe.foundation.coreagent.coding.patches.task_tool import (
    apply_task_tool_patch,
    general_purpose_subagent_build_context,
)

__all__ = [
    "apply_execute_tool_removal_patch",
    "without_deepagents_execute_tool",
    "apply_summarization_patches",
    "apply_task_tool_patch",
    "general_purpose_subagent_build_context",
]
