"""Goal completion decision policy (RFC-219, IG-298, IG-299).

Unified decision logic combining hybrid assessment with completion action selection.
Consolidated from synthesis_policy.py and strategy selection (IG-299).

Decision flow:
1. Goal completion needs: LLM and/or heuristics per ``mode`` (``determine_goal_completion_needs``)
2. Completion action: skip/direct/synthesis/summary (``determine_completion_action``)

Decision modes (``determine_goal_completion_needs`` ``mode``):
- llm_only: Trust LLM decision completely (no heuristic fallback; default)
- heuristic_only: Ignore LLM, use execution metrics only
- hybrid: LLM primary, heuristic fallback when LLM returns false

``state.last_execute_assistant_text`` is resolved per wave by
:mod:`soothe.core.agent_loop.core.act_wave_finalize` from root assistant stream text and/or
ordered ``task`` tool return bodies (IG-355, IG-357).

Heuristic categories (execution-focused, IG-298):
- Wave execution: Parallel multi-step, subagent cap
- DAG complexity: Rich dependency edges on the current plan
- Completion quality: Failed steps with low success rate

Removed: Word count, evidence vs output ratio (output metrics unreliable).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal

    from soothe.core.agent_loop.state.schemas import LoopState, PlanResult

    FinalResponseMode = Literal["adaptive", "always_synthesize", "always_last_execute"]

logger = logging.getLogger(__name__)

# Execution complexity thresholds (IG-298)
_DAG_DEPENDENCY_THRESHOLD = 3  # dag dependencies indicates complex orchestration
_LOW_SUCCESS_RATE_THRESHOLD = 0.6  # lower success rate needs explanation

# Structural fallbacks threshold (IG-300).
_STRUCTURED_PAYLOAD_MIN_LINES = 6


def determine_goal_completion_needs(
    llm_decision: bool,
    state: TYPE_CHECKING.Any,  # LoopState
    mode: str = "llm_only",
) -> bool:
    """Decide whether goal-completion synthesis/reporting is required (RFC-219, IG-298).

    Priority by ``mode``:
    - ``llm_only``: Return ``llm_decision`` (``StatusAssessment.require_goal_completion``).
    - ``heuristic_only``: Return execution-heuristic result only.
    - ``hybrid``: True if LLM says true; else heuristic fallback when LLM is false.

    Args:
        llm_decision: LLM's require_goal_completion from StatusAssessment.
        state: Loop state with execution history and wave metrics.
        mode: ``llm_only`` (default), ``heuristic_only``, or ``hybrid``. Configure via
            ``agentic.goal_completion_mode`` in YAML.

    Returns:
        Final require_goal_completion decision.
    """
    if mode == "llm_only":
        logger.debug("GoalCompletion: mode=llm_only result=%s", llm_decision)
        return llm_decision

    if mode == "heuristic_only":
        result = _heuristic_requires_goal_completion(state)
        logger.debug("GoalCompletion: mode=heuristic_only result=%s", result)
        return result

    # Hybrid mode: LLM primary, heuristic fallback
    if llm_decision:
        logger.debug("GoalCompletion: mode=hybrid LLM=True (honored)")
        return True

    # Heuristic fallback when LLM returns False
    heuristic_result = _heuristic_requires_goal_completion(state)
    if heuristic_result:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=True")
    else:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=False (skip)")

    return heuristic_result


def _heuristic_requires_goal_completion(state: TYPE_CHECKING.Any) -> bool:
    """Check execution complexity indicators requiring synthesis.

    Simplified heuristics (IG-298):
    - Execution complexity (parallel multi-step, subagent cap)
    - Completion quality (failed steps needing explanation)
    - DAG edges on the current plan

    Removed word count metrics (output-focused, unreliable).

    Args:
        state: Loop state with execution history.

    Returns:
        True if execution complexity suggests synthesis needed.
    """
    # 1. Wave execution complexity (IG-130, IG-132)
    if state.last_execute_wave_parallel_multi_step:
        logger.info("Heuristic: parallel_multi_step=True")
        return True

    if state.last_wave_hit_subagent_cap:
        logger.info("Heuristic: subagent_cap=True")
        return True

    # 2. Completion quality: failed steps need explanation
    failed_count = sum(1 for r in state.step_results if not r.success)
    if failed_count > 0:
        # Failed steps with low success rate need synthesis
        total = len(state.step_results)
        success_rate = (total - failed_count) / total if total > 0 else 0.0
        if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
            logger.info("Heuristic: failed_steps (rate=%.0f%%)", success_rate * 100)
            return True
        # Failed steps with high success rate don't need synthesis
        # Return False early to avoid triggering on step count
        logger.debug(
            "Heuristic: failed_steps_high_success (rate=%.0f%%) → skip", success_rate * 100
        )
        # Don't return — continue to DAG check

    # 3. DAG dependencies on the current plan
    if state.current_decision:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
            for step in state.current_decision.steps
        )
        if has_deps:
            logger.info("Heuristic: dag_dependencies=True")
            return True

    logger.debug("Heuristic: simple_execution (skip synthesis)")
    return False


def determine_completion_action(
    state: LoopState,
    plan_result: PlanResult,
    mode: FinalResponseMode = "adaptive",
) -> tuple[str, str | None]:
    """Single entry point for completion decision and action (IG-300).

    Consolidates strategy selection from synthesis_policy and completion_strategies.
    Returns action and optional precomputed text for direct/skip branches.

    Args:
        state: Loop state with execution history.
        plan_result: Plan result with planner's hybrid decision.
        mode: Final-response mode (adaptive, always_synthesize, always_last_execute).

    Returns:
        (action, precomputed_text) where action in {"skip", "direct", "synthesize", "summary"}
        and precomputed_text is reuse text for skip/direct, None for synthesize/summary.
    """
    # 1. Mode overrides
    if mode == "always_synthesize":
        return "synthesize", None

    if mode == "always_last_execute":
        assistant = (state.last_execute_assistant_text or "").strip()
        return ("direct", assistant) if assistant else ("summary", None)

    # 2. Planner skip: trust hybrid decision (IG-298)
    if not plan_result.require_goal_completion:
        reuse = (state.last_execute_assistant_text or "").strip()
        return "skip", reuse

    # 3. Wave execution vetoes
    if state.last_execute_wave_parallel_multi_step:
        return "synthesize", None

    if state.last_wave_hit_subagent_cap:
        return "synthesize", None

    # 4. Direct return check: richness + overlap
    assistant = (state.last_execute_assistant_text or "").strip()
    if not assistant:
        return "synthesize", None

    if _can_return_directly(assistant, plan_result):
        return "direct", assistant

    # 5. Synthesis needed per planner + execution complexity
    return "synthesize", None


def _can_return_directly(
    assistant_text: str,
    plan_result: PlanResult,
) -> bool:
    """Check richness (structure) + overlap with planner output (IG-300).

    Args:
        assistant_text: Execute assistant output.
        plan_result: Plan result with full_output for overlap check.

    Returns:
        True if output is rich enough and aligned with planner.
    """
    # Richness check (IG-300: simplified, no length category)
    if not _is_rich_enough(assistant_text):
        return False

    # Overlap check (avoid unrelated chatter)
    return _overlaps_with_plan_output(assistant_text, plan_result)


def _is_rich_enough(assistant_text: str) -> bool:
    """Heuristic guard for rich, user-facing completion content (IG-300).

    Simplified from IG-273: checks for structured payloads or sufficient content.
    No word count thresholds - judges from structure alone.
    """
    text = assistant_text.strip()
    if not text:
        return False

    # Accept structured payloads (code fences, multi-line lists)
    if "```" in text:
        return True

    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if len(non_empty_lines) >= _STRUCTURED_PAYLOAD_MIN_LINES:
        return True

    # Accept responses with sufficient length (heuristic: >100 chars)
    return len(text) >= 100


def _overlaps_with_plan_output(assistant_text: str, plan_result: PlanResult) -> bool:
    """Return True when Execute text appears to reflect the planner's full_output (IG-299).

    Used only as an adaptive-mode veto signal: if the planner captured a distinct
    full_output and the Execute assistant text shares no common substring with it,
    we assume Execute did not actually answer the goal and require synthesis.
    """
    plan_out = (plan_result.full_output or "").strip()
    if not plan_out:
        # No planner reference available; do not veto on this signal.
        return True

    assistant_lower = assistant_text.lower()
    # Sample the first chunk of plan output for a lightweight overlap probe.
    probe = plan_out[:160].lower()
    if not probe.strip():
        return True

    # Split on whitespace and keep substantive tokens (avoid stopwords-ish noise).
    tokens = [t for t in re.split(r"\W+", probe) if len(t) >= 4]
    if not tokens:
        return True

    hits = sum(1 for t in tokens if t in assistant_lower)
    # Require at least 25% token overlap to accept direct return.
    return hits * 4 >= len(tokens)
