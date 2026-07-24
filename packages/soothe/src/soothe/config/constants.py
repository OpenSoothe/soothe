"""Global constants for Soothe configuration.

This module defines default values and limits used across the framework.
Centralizing constants ensures consistency and easier maintenance.

Shared execution-tool limits (``DEFAULT_EXECUTE_TIMEOUT``,
``MAX_EXECUTE_TIMEOUT``, ``DEFAULT_TASK_TIMEOUT_SECONDS``,
``clamp_execute_timeout``, ``DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS``,
``DEFAULT_TOOL_OUTPUT_CHARS``) are owned by ``soothe_nano.config.constants``
and re-exported here so host consumers keep a single import surface. Host-only
iteration/budget limits stay local.
"""

# Re-export facade — canonical source: soothe_nano.config.constants
from soothe_nano.config.constants import (  # noqa: F401
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
    DEFAULT_EXECUTE_TIMEOUT,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    DEFAULT_TOOL_OUTPUT_CHARS,
    MAX_EXECUTE_TIMEOUT,
    clamp_execute_timeout,
)

# ============================================================================
# Agent Loop Iteration Limits
# ============================================================================

# Default maximum iterations for agent loop execution (RFC-201)
# Higher values allow more complex multi-step reasoning and execution
DEFAULT_MAX_ITERATIONS = 99

# Per execute-step cap on root-graph tool results consumed from the Act stream.
DEFAULT_MAX_TOOL_CALLS_PER_STEP = 999

# Back-compat alias
DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = DEFAULT_MAX_ITERATIONS
