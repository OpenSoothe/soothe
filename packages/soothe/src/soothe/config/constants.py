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
# Autonomous Goal Management Limits
# ============================================================================

# Default maximum iterations per autonomous thread (RFC-0007)
DEFAULT_AUTONOMOUS_MAX_ITERATIONS = 10

# ============================================================================
# Execution Tool Limits
# ============================================================================

# Default timeout for shell command execution (RFC-606 TUI migration)
# Used by execution tools (run_command) and TUI display logic
DEFAULT_EXECUTE_TIMEOUT = 60  # seconds

# Max chars for shell/code tool stdout (run_command) and code_exec aggregation in StrangeLoop execute.
DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS = 100_000

# Max chars for non-code_exec tool output in StrangeLoop execute-stream aggregation.
DEFAULT_TOOL_OUTPUT_CHARS = 10_000

# ============================================================================
# Early Termination Thresholds
# ============================================================================

# Maximum consecutive empty tool calls before early termination
MAX_CONSECUTIVE_EMPTY_TOOL_CALLS = 2

# Maximum evidence string length for final stdout display
MAX_EVIDENCE_STRING_LENGTH = 500

# ============================================================================
# Conversation Context Limits
# ============================================================================

# Default limit for recent messages loaded for classification
DEFAULT_RECENT_MESSAGES_FOR_CLASSIFY_LIMIT = 10

# Default limit for prior conversation excerpts in plan prompts
DEFAULT_PRIOR_CONVERSATION_LIMIT = 10
