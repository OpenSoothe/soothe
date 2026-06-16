"""Runtime compatibility patches (aggregated shim).

Patches are applied at import time and isolated from CoreAgent logic.
These patches fix upstream issues that affect Soothe's execution.

The actual patch implementations have been split into focused modules:
- _patch_summarization.py: SummarizationMiddleware patches
- _patch_task_tool.py: task tool config propagation patch

This module remains as a shim for backward compatibility and
aggregates all patches for easy import by _builder.py.
"""

from __future__ import annotations

# Import from split modules (all imports at top per E402)
from soothe.foundation.core.agent._patch_summarization import (
    _TOOLS_TOKEN_CACHE,
    _cached_tools_token_count,
    _patch_summarization_overwrite_handling,
    _patch_summarization_token_count_optimization,
    _split_conversation_token_count,
    _tools_token_cache_key,
    apply_summarization_patches,
)
from soothe.foundation.core.agent._patch_task_tool import (
    _patch_task_tool_propagates_parent_runnable_config,
    apply_task_tool_patch,
)

# Apply all patches at module import time
apply_summarization_patches()
apply_task_tool_patch()

__all__ = [
    "apply_summarization_patches",
    "apply_task_tool_patch",
    "_patch_summarization_overwrite_handling",
    "_patch_summarization_token_count_optimization",
    "_patch_task_tool_propagates_parent_runnable_config",
    "_tools_token_cache_key",
    "_TOOLS_TOKEN_CACHE",
    "_cached_tools_token_count",
    "_split_conversation_token_count",
]
