"""Global constants for Soothe configuration."""

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
# Simple tasks may decompose mid-step: the model gathers evidence, then invokes
# decompose_task to fan out subtasks when the goal is bigger than one step. 500
# gives room for that explore→decompose trajectory; the iteration budget
# (DEFAULT_MAX_ITERATIONS) and consecutive rate-limit gate still bound runaway.
DEFAULT_MAX_TOOL_CALLS_PER_STEP = 500

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

# ── Goal completion report projection ───────────────────────────────────────
# Bounds the prior-goal completion report (synthesis output) when projected
# forward into intake classify, plan, execute, and synthesis prompts. 100k
# accommodates the full ~60k reports seen in practice with headroom. When a
# report exceeds the char cap, it is truncated head+tail (40% beginning +
# 60% tail) rather than front-only, so conclusions/recommendations survive.
GOAL_COMPLETION_REPORT_MAX_CHARS: int = 100_000
GOAL_COMPLETION_REPORT_MAX_MESSAGES: int = 500
GOAL_COMPLETION_REPORT_MAX_PER_MESSAGE_CHARS: int = 100_000
