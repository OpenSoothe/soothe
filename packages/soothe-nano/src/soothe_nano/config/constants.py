"""Global constants for Coding CoreAgent configuration.

Centralizing defaults keeps tool timeouts and output caps consistent.
"""

# ============================================================================
# Execution Tool Limits
# ============================================================================

# Default timeout for shell command execution
# Used by execution tools (run_command) and TUI display logic
DEFAULT_EXECUTE_TIMEOUT = 60  # seconds

# Upper bound for per-call run_command timeout (LLM arg and middleware ceiling)
MAX_EXECUTE_TIMEOUT = 18000  # 5 hours

# Default timeout for the task tool (subagent delegation)
DEFAULT_TASK_TIMEOUT_SECONDS = 18000  # 5 hours


def clamp_execute_timeout(seconds: int | float) -> int:
    """Clamp run_command timeout to ``MAX_EXECUTE_TIMEOUT``."""
    return min(int(seconds), MAX_EXECUTE_TIMEOUT)


# Max chars for shell/code tool stdout (run_command) and code_exec aggregation.
DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS = 100_000

# Max chars for non-code_exec tool output in stream aggregation.
DEFAULT_TOOL_OUTPUT_CHARS = 10_000
