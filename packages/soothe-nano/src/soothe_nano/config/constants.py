"""Global constants for Soothe configuration.

This module defines default values and limits used across the framework.
Centralizing constants ensures consistency and easier maintenance.
"""

# ============================================================================
# Agent Loop Iteration Limits
# ============================================================================

# Default maximum iterations for StrangeLoop execution (RFC-201)
# Higher values allow more complex multi-step reasoning and execution
DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = 99

# ============================================================================
# Execution Tool Limits
# ============================================================================

# Default timeout for shell command execution (RFC-606 TUI migration)
# Used by execution tools (run_command) and TUI display logic
DEFAULT_EXECUTE_TIMEOUT = 60  # seconds

# Upper bound for per-call run_command timeout (LLM arg and middleware ceiling)
MAX_EXECUTE_TIMEOUT = 18000  # 5 hours

# Default timeout for the task tool (subagent delegation)
DEFAULT_TASK_TIMEOUT_SECONDS = 18000  # 5 hours


def clamp_execute_timeout(seconds: int | float) -> int:
    """Clamp run_command timeout to ``MAX_EXECUTE_TIMEOUT``."""
    return min(int(seconds), MAX_EXECUTE_TIMEOUT)


# Max chars for shell/code tool stdout (run_command) and code_exec aggregation in StrangeLoop execute.
DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS = 100_000

# Max chars for non-code_exec tool output in StrangeLoop execute-stream aggregation.
DEFAULT_TOOL_OUTPUT_CHARS = 10_000

# Per execute-step cap on root-graph tool results consumed from the Act stream.
DEFAULT_MAX_TOOL_CALLS_PER_STEP = 999
