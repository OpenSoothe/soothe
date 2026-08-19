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
# SEC: 999 is an open door to runaway tool loops. 100 is sufficient for complex
# multi-tool workflows while bounding cost and resource exhaustion.
DEFAULT_MAX_TOOL_CALLS_PER_STEP = 100

# Back-compat alias
DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = DEFAULT_MAX_ITERATIONS

# ============================================================================
# Prompt / Render Character-Cap Registry
# ============================================================================
#
# Every *_CHARS / *_MAX_CHARS sentinel that bounds text fed to an LLM prompt
# or rendered TUI surface lives here so operators and reviewers can audit
# truncation budgets in one place.

# ── Selector rails field caps ───────────────────────────────────────────────

DEFAULT_MAX_FIELD_CHARS: int = 2000
DEFAULT_MAX_DESCRIPTION_CHARS: int = 2000

# ── Phase / evidence summary ────────────────────────────────────────────────

_EVIDENCE_SUMMARY_MAX_CHARS: int = 2000

# ── Vision context brief ────────────────────────────────────────────────────

VISION_CONTEXT_MAX_CHARS: int = 4000
VISION_BRIEF_IMAGE_FACTS_MAX_CHARS: int = 4000

# ── Continuation & predecessor context ──────────────────────────────────────

CONTINUATION_ASSESS_REASONING_MAX_CHARS: int = 240
PRIOR_STEP_EVIDENCE_MAX_CHARS: int = 4000
PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS: int = 160

# ── Pass-2 intention classifier ─────────────────────────────────────────────

_PASS2_PRIOR_MAX_CHARS: int = 2400
_PASS2_REASONING_MAX_CHARS: int = 200

# ── Planner assembly ────────────────────────────────────────────────────────

GOAL_PREVIEW_MAX_CHARS: int = 120
